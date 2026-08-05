"""scheduler 管理器：注册 / 启停 / 启用禁用 / 立即执行 / 历史"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.scheduler.cron_human import cron_to_human
from src.scheduler.history import JSONLReaderWriter, build_record
from src.scheduler.jobs import JOB_TARGETS
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class SchedulerManager:
    """内建 APScheduler 管理器。

    - 启动时从 config_path 加载 3 个预设任务，注册到 AsyncIOScheduler
    - MemoryJobStore（默认，零持久化），任务定义来自 config 文件
    - 启用/禁用立即生效，且写回 config 文件
    - 立即执行用 DateTrigger 一次性触发，cron job 不受影响
    """

    def __init__(
        self,
        port: int,
        config_path: Path,
        history_path: Path,
    ) -> None:
        self.port = port
        self._config_path = Path(config_path)
        self._history = JSONLReaderWriter(history_path)
        self._scheduler: AsyncIOScheduler | None = None
        self._services: dict = {}
        # job_id → config dict（内存缓存）
        self.jobs_meta: dict[str, dict] = {}
        # job_id → asyncio.Lock（防 trigger_now 与 cron 重入）
        self._run_locks: dict[str, asyncio.Lock] = {}

    # === lifecycle ===

    def start(self, services: dict) -> None:
        """启动 scheduler。services 必须含 data_reader。"""
        if self._scheduler is not None:
            logger.warning("scheduler 已启动，忽略 start")
            return
        self._assert_single_worker()

        self._services = services
        config = self._load_config()
        self.jobs_meta = {j["id"]: j for j in config.get("jobs", [])}

        scheduler = AsyncIOScheduler(
            job_defaults={
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        )
        for job_cfg in self.jobs_meta.values():
            job_id = job_cfg["id"]
            self._run_locks[job_id] = asyncio.Lock()
            try:
                trigger = CronTrigger.from_crontab(job_cfg["cron"])
            except Exception as e:
                logger.error(f"[{job_id}] cron 解析失败: {e}")
                continue
            scheduler.add_job(
                self._run_job_wrapper,
                trigger,
                id=job_id,
                args=[job_id],
                replace_existing=True,
            )
            if not job_cfg.get("enabled", True):
                scheduler.pause_job(job_id)
            logger.info(
                f"[{job_id}] 注册: cron={job_cfg['cron']} "
                f"({cron_to_human(job_cfg['cron'])}) "
                f"enabled={job_cfg.get('enabled', True)} "
                f"target={job_cfg['target']}"
            )
        scheduler.start()
        self._scheduler = scheduler
        logger.info(f"scheduler 启动完成，{len(self.jobs_meta)} 个任务")

    async def shutdown(self, wait: bool = True, timeout: int = 30) -> None:
        if self._scheduler is None:
            return
        logger.info(f"scheduler 关闭中（wait={wait}, timeout={timeout}s）...")
        try:
            self._scheduler.shutdown(wait=wait, timeout=timeout)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(f"scheduler shutdown 异常: {e}")
        finally:
            self._scheduler = None

    # === API ===

    def list_jobs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for job_id, spec in self.jobs_meta.items():
            sched_job = (
                self._scheduler.get_job(job_id) if self._scheduler else None
            )
            next_run = (
                sched_job.next_run_time.isoformat()
                if sched_job and sched_job.next_run_time
                else None
            )
            last_runs = self._history.read_tail(job_id=job_id, n=1)
            last_run = last_runs[0] if last_runs else None
            result.append(
                {
                    "id": job_id,
                    "name": spec.get("name", job_id),
                    "target": spec["target"],
                    "cron": spec["cron"],
                    "cron_human": cron_to_human(spec["cron"]),
                    "enabled": spec.get("enabled", True),
                    "next_run_time": next_run,
                    "last_run": _slim_last_run(last_run),
                    "description": spec.get("description", ""),
                }
            )
        return result

    def set_enabled(self, job_id: str, enabled: bool) -> dict[str, Any]:
        if job_id not in self.jobs_meta:
            raise KeyError(job_id)
        if self._scheduler is None:
            raise RuntimeError("scheduler 未启动")
        self.jobs_meta[job_id]["enabled"] = enabled
        self._write_config()
        if enabled:
            self._scheduler.resume_job(job_id)
            logger.info(f"[{job_id}] 已启用")
        else:
            self._scheduler.pause_job(job_id)
            logger.info(f"[{job_id}] 已禁用")
        # 返回更新后的 job（list_jobs 重新读 history 拿 last_run）
        return next(j for j in self.list_jobs() if j["id"] == job_id)

    async def trigger_now(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs_meta:
            raise KeyError(job_id)
        if self._scheduler is None:
            raise RuntimeError("scheduler 未启动")
        triggered_at = datetime.now().isoformat()
        # 一次性任务：用 DateTrigger 立即触发；id 加后缀避免与 cron job 冲突
        run_id = f"{job_id}_manual_{int(datetime.now().timestamp() * 1000)}"
        self._scheduler.add_job(
            self._run_job_wrapper,
            DateTrigger(run_date=datetime.now()),
            id=run_id,
            args=[job_id],
            replace_existing=False,
        )
        logger.info(f"[{job_id}] 手动触发 @ {triggered_at} (run_id={run_id})")
        return {"job_id": job_id, "triggered_at": triggered_at}

    def get_job_runs(self, job_id: str, limit: int = 20) -> list[dict[str, Any]]:
        if job_id not in self.jobs_meta:
            raise KeyError(job_id)
        return self._history.read_tail(job_id=job_id, n=limit)

    # === helpers ===

    def get_holdings_codes(self) -> list[str]:
        """从 data_reader 读 CSV 第一列作为持仓 codes。"""
        dr = self._services.get("data_reader")
        if dr is None:
            return []
        df = dr.read_csv()
        if df is None or df.empty:
            return []
        code_col = df.columns[0]
        return df[code_col].astype(str).str.zfill(6).tolist()

    async def _run_job_wrapper(self, job_id: str) -> None:
        """APScheduler 调用入口：查 target → 调 jobs.{target} → 写历史。"""
        spec = self.jobs_meta.get(job_id)
        if spec is None:
            logger.warning(f"未知 job_id: {job_id}")
            return
        target_name = spec["target"]
        target_fn = JOB_TARGETS.get(target_name)
        if target_fn is None:
            logger.error(f"[{job_id}] 未知 target: {target_name}")
            return
        # 防重入：cron 触发 vs trigger_now 同时进来时串行化
        lock = self._run_locks.setdefault(job_id, asyncio.Lock())
        async with lock:
            logger.info(f"[{job_id}] 开始执行 target={target_name}")
            try:
                result = await target_fn(self, job_id)
            except Exception as e:
                logger.exception(f"[{job_id}] target 抛异常")
                now_iso = datetime.now().isoformat()
                result = {
                    "status": "failed",
                    "error": f"unhandled: {e}",
                    "start": now_iso,
                    "end": now_iso,
                }
            result.setdefault("start", datetime.now().isoformat())
            result.setdefault("end", datetime.now().isoformat())
            record = build_record(
                job_id=job_id,
                target=target_name,
                start=result["start"],
                end=result["end"],
                status=result.get("status", "failed"),
                count=result.get("count"),
                reason=result.get("reason"),
                error=result.get("error"),
            )
            await self._history.append(record)
            logger.info(
                f"[{job_id}] 执行结束 status={record['status']} "
                f"count={record.get('count')} reason={record.get('reason')}"
            )

    def _load_config(self) -> dict:
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            logger.error(
                f"scheduler 配置文件不存在: {self._config_path} — "
                "调度器将不注册任何任务。检查挂载卷或重新 build 镜像。"
            )
            return {"version": 1, "jobs": []}
        except Exception as e:
            logger.error(f"scheduler 配置加载失败: {e}")
            return {"version": 1, "jobs": []}

        # 关键：jobs 为空时常因 volume 覆盖导致，运维侧需要明显感知
        if not cfg.get("jobs"):
            logger.error(
                "scheduler 配置加载成功但 jobs 列表为空 — "
                "调度器将不注册任何任务！"
                "检查 /app/config/scheduler.json 是否被 volume 覆盖，"
                "或 config_path 路径是否正确。"
            )
        return cfg

    def _write_config(self) -> None:
        """把内存中 jobs_meta 写回 config 文件（保留原始字段顺序）。"""
        out = {"version": 1, "jobs": list(self.jobs_meta.values())}
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"scheduler 配置写回失败: {e}")

    def _assert_single_worker(self) -> None:
        """多 worker 启动时拒绝（NFR-4）。"""
        workers_str = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
        if workers_str and workers_str.isdigit() and int(workers_str) > 1:
            raise RuntimeError(
                f"scheduler 要求单 worker 模式，检测到 workers={workers_str}。"
                "请用 --workers 1 或 unset WEB_CONCURRENCY/UVICORN_WORKERS"
            )


def _slim_last_run(rec: dict | None) -> dict | None:
    """精简 last_run 字段（job_id/target 已在 job 顶层）。"""
    if rec is None:
        return None
    return {
        "start": rec.get("start"),
        "end": rec.get("end"),
        "status": rec.get("status"),
        "count": rec.get("count"),
        "reason": rec.get("reason"),
        "error": rec.get("error"),
    }
