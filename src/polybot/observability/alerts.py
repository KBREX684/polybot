from __future__ import annotations

import json
from typing import Any

import requests

from src.polybot.observability.logger import get_logger

log = get_logger("alerts")


class AlertChannel:
    def send(self, title: str, message: str, level: str = "info") -> bool:
        raise NotImplementedError


class TelegramChannel(AlertChannel):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, title: str, message: str, level: str = "info") -> bool:
        emoji = {"info": "📊", "warning": "⚠️", "error": "🔴", "trade": "💰", "critical": "🚨"}.get(level, "📌")
        text = f"{emoji} *{title}*\n\n{message}"
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as exc:
            log.error("telegram_send_failed", error=str(exc))
            return False


class DiscordChannel(AlertChannel):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, level: str = "info") -> bool:
        color = {"info": 3447003, "warning": 16776960, "error": 15158332, "trade": 5763719, "critical": 15158332}.get(level, 3447003)
        payload = {
            "embeds": [{"title": title, "description": message[:2000], "color": color}],
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in {200, 204}
        except Exception as exc:
            log.error("discord_send_failed", error=str(exc))
            return False


class SlackChannel(AlertChannel):
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, title: str, message: str, level: str = "info") -> bool:
        payload = {"text": f"*{title}*\n{message}"}
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as exc:
            log.error("slack_send_failed", error=str(exc))
            return False


class AlertManager:
    """Multi-channel alert manager with cooldown support."""

    def __init__(
        self,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        discord_webhook: str = "",
        slack_webhook: str = "",
        cooldown_seconds: int = 300,
    ) -> None:
        self.channels: list[AlertChannel] = []
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}

        if telegram_bot_token and telegram_chat_id:
            self.channels.append(TelegramChannel(telegram_bot_token, telegram_chat_id))
        if discord_webhook:
            self.channels.append(DiscordChannel(discord_webhook))
        if slack_webhook:
            self.channels.append(SlackChannel(slack_webhook))

    def alert(self, title: str, message: str, level: str = "info", force: bool = False) -> bool:
        if not self.channels:
            return False

        import time
        key = f"{title}:{level}"
        now = time.monotonic()
        if not force:
            last = self._last_sent.get(key, 0)
            if now - last < self.cooldown_seconds:
                return False

        self._last_sent[key] = now
        results = [ch.send(title, message, level) for ch in self.channels]
        return any(results)

    def alert_trade_executed(self, market_id: str, side: str, size_usdc: float, edge: float) -> None:
        self.alert(
            "Trade Executed",
            f"Market: `{market_id}`\nSide: {side}\nSize: ${size_usdc:.2f}\nEdge: {edge:.4f}",
            level="trade",
        )

    def alert_drawdown_warning(self, level: str, drawdown_pct: float) -> None:
        self.alert(
            f"Drawdown {level.upper()}",
            f"Current drawdown: {drawdown_pct:.1%}\nPosition sizing reduced.",
            level="warning",
        )

    def alert_kill_switch(self) -> None:
        self.alert(
            "Kill Switch Activated",
            "All trading halted. Positions being force-closed.",
            level="critical",
            force=True,
        )

    def alert_daily_loss(self, loss_usdc: float, limit_usdc: float) -> None:
        self.alert(
            "Daily Loss Limit",
            f"Daily loss: ${loss_usdc:.2f} / ${limit_usdc:.2f}\nTrading paused until tomorrow.",
            level="warning",
        )

    def alert_llm_failure(self, model: str, consecutive_failures: int) -> None:
        if consecutive_failures >= 3:
            self.alert(
                "LLM Consecutive Failures",
                f"Model: {model}\nConsecutive failures: {consecutive_failures}",
                level="error",
            )

    def alert_cycle_summary(self, summary: dict[str, Any]) -> None:
        msg = "\n".join(f"{k}: {v}" for k, v in summary.items() if isinstance(v, (int, float, str, bool)))
        self.alert("Cycle Summary", msg, level="info")
