"""
钉钉机器人 webhook 推送

环境变量:
    DINGTALK_WEBHOOK_URL  钉钉机器人 webhook 地址（不配则跳过推送）
"""
import os
from typing import Optional

import requests

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DingTalkNotifier:
    """
    钉钉机器人 markdown 推送

    未配置 webhook 时所有方法返回 False / 静默，方便本地开发。
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = (
            webhook_url if webhook_url is not None else os.getenv("DINGTALK_WEBHOOK_URL", "")
        ).strip() or None

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send_markdown(self, title: str, text: str) -> bool:
        """
        发送 markdown 消息

        Returns:
            True = 发送成功；False = 未配置 / 发送失败 / 钉钉返回非 0 errcode
        """
        if not self.is_configured():
            logger.info("DINGTALK_WEBHOOK_URL 未配置，跳过推送")
            return False

        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            data = resp.json()
        except Exception as e:
            logger.error(f"钉钉推送异常: {e}", exc_info=True)
            return False

        if resp.status_code == 200 and data.get("errcode") == 0:
            return True

        logger.error(
            f"钉钉推送失败: status={resp.status_code} errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
        )
        return False

    def send_alerts(self, triggered: list) -> bool:
        """
        汇总推送挡位触发列表（卖在前买在后，markdown 表格）

        钉钉机器人关键词过滤：消息必须包含 "交易" 才会发送成功。

        Args:
            triggered: AlertService.check_all() 返回的 triggered 列表
        """
        if not triggered:
            return True

        today = triggered[0]["triggered_at"][:10]
        title = f"交易挡位提醒 {today}（共{len(triggered)}只）"

        lines = [
            f"# 📈 交易挡位触发提醒 ({today})",
            "",
            f"今日共 **{len(triggered)}** 只股票触发交易挡位：",
            "",
        ]

        sells = [t for t in triggered if t["direction"] == "sell"]
        buys = [t for t in triggered if t["direction"] == "buy"]

        if sells:
            lines.append("## 🔴 卖出信号")
            lines.append("")
            lines.append("| 股票 | 档位 | 现价 | 挡位价 | PE (现/档) | 距离 |")
            lines.append("|------|------|-----:|-------:|-----------|-----:|")
            for t in sells:
                lines.append(self._format_row(t))
            lines.append("")

        if buys:
            lines.append("## 🟢 买入信号")
            lines.append("")
            lines.append("| 股票 | 档位 | 现价 | 挡位价 | PE (现/档) | 距离 |")
            lines.append("|------|------|-----:|-------:|-----------|-----:|")
            for t in buys:
                lines.append(self._format_row(t))
            lines.append("")

        # 附第一条策略摘要（避免消息过长）
        first = triggered[0]
        if first.get("strategy"):
            star = "⭐" * (first.get("star_rating") or 0)
            strategy_brief = first["strategy"][:80]
            lines.append(f"> {star} {first['name']}：{strategy_brief}")

        # 钉钉机器人关键词校验：必须含 "交易"（已多处出现，这里再加一行兜底）
        lines.append("")
        lines.append("> ⚠️ 自动推送 · 来自交易挡位监控系统")

        return self.send_markdown(title, "\n".join(lines))

    @staticmethod
    def _format_row(t: dict) -> str:
        pe_str = DingTalkNotifier._fmt_pe(t.get("current_pe"), t.get("level_pe"))
        return (
            f"| {t['name']}({t['code']}) "
            f"| {t['level_emoji']}{t['level_label']} "
            f"| ¥{t['current_price']:.2f} "
            f"| ¥{t['level_price']:.2f} "
            f"| {pe_str} "
            f"| {t['distance_pct']:+.2f}% |"
        )

    @staticmethod
    def _fmt_pe(current_pe, level_pe) -> str:
        cur = f"{current_pe:.1f}x" if isinstance(current_pe, (int, float)) else "-"
        lvl = f"{level_pe:.1f}x" if isinstance(level_pe, (int, float)) else "-"
        return f"{cur} / {lvl}"
