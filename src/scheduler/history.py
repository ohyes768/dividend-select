"""scheduler 执行历史 JSONL 读写"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

_DEFAULT_MAX_SIZE_MB = 5
_DEFAULT_TAIL_N = 200


class JSONLReaderWriter:
    """JSONL 追加写 + 尾部读，支持按 job_id 过滤和大小滚动。

    写入是 asyncio.Lock 串行化，避免并发 job 写入交错。
    """

    def __init__(
        self,
        history_path: Path,
        max_size_mb: int = _DEFAULT_MAX_SIZE_MB,
    ) -> None:
        self._path = Path(history_path)
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = asyncio.Lock()
        # 父目录不存在则建
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 文件不存在则建空
        if not self._path.exists():
            self._path.touch()

    async def append(self, record: dict[str, Any]) -> None:
        """追加一行记录。失败 warn 但不抛（NFR-6）。"""
        line = json.dumps(record, ensure_ascii=False)
        try:
            async with self._lock:
                self._maybe_rotate()
                # POSIX 下小写入 + O_APPEND 是原子的；Windows 下加 Lock 串行化兜底
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception as e:
            logger.warning(f"写入 scheduler 历史失败（不影响主流程）: {e}")

    def read_tail(
        self,
        job_id: str | None = None,
        n: int = _DEFAULT_TAIL_N,
    ) -> list[dict[str, Any]]:
        """从尾部往前读 n 条，可选按 job_id 过滤。解析失败的行跳过。"""
        if not self._path.exists():
            return []
        try:
            # 反向 chunked 读
            with open(self._path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                chunk = 8192
                collected: list[bytes] = []
                pos = size
                lines_needed = n
                while pos > 0 and lines_needed > 0:
                    read_size = min(chunk, pos)
                    pos -= read_size
                    f.seek(pos)
                    data = f.read(read_size)
                    collected.append(data)
                    # 计算已有完整行数
                    joined = b"".join(reversed(collected))
                    newline_count = joined.count(b"\n")
                    if newline_count >= lines_needed:
                        break
                joined = b"".join(reversed(collected))
                lines = joined.decode("utf-8", errors="replace").splitlines()
                # 取最后 n 条
                tail = lines[-n:] if len(lines) >= n else lines
            results: list[dict[str, Any]] = []
            for line in reversed(tail):  # 倒序：最新在前
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if job_id is not None and rec.get("job_id") != job_id:
                    continue
                results.append(rec)
            return results
        except Exception as e:
            logger.warning(f"读取 scheduler 历史失败: {e}")
            return []

    def _maybe_rotate(self) -> None:
        """超过 max_size_bytes 时滚动为 scheduler_runs.YYYYMMDD.jsonl"""
        try:
            if not self._path.exists():
                return
            if self._path.stat().st_size < self._max_size_bytes:
                return
            ts = datetime.now().strftime("%Y%m%d")
            archive_path = self._path.with_name(f"{self._path.stem}.{ts}{self._path.suffix}")
            # 同一天已存在归档时加序号
            counter = 1
            while archive_path.exists():
                archive_path = self._path.with_name(
                    f"{self._path.stem}.{ts}.{counter}{self._path.suffix}"
                )
                counter += 1
            os.replace(self._path, archive_path)
            self._path.touch()
            logger.info(f"scheduler 历史滚动: {archive_path.name}")
            # 清理旧归档：保留最近 3 个
            self._cleanup_old_archives()
        except Exception as e:
            logger.warning(f"scheduler 历史滚动失败（继续使用原文件）: {e}")

    def _cleanup_old_archives(self) -> None:
        """保留最近 3 个归档，删旧的"""
        try:
            stem = self._path.stem
            suffix = self._path.suffix
            archives = sorted(
                self._path.parent.glob(f"{stem}.*{suffix}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in archives[3:]:
                old.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"清理旧 scheduler 归档失败: {e}")


def build_record(
    job_id: str,
    target: str,
    start: str,
    end: str,
    status: str,
    count: int | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """统一构造历史记录字段，保证 schema 稳定"""
    rec: dict[str, Any] = {
        "job_id": job_id,
        "target": target,
        "start": start,
        "end": end,
        "status": status,
        "error": error,
    }
    if count is not None:
        rec["count"] = count
    if reason is not None:
        rec["reason"] = reason
    return rec
