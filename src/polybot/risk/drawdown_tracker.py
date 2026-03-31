from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from src.polybot.schemas import DrawdownLevel


class DrawdownTracker:
    def __init__(
        self,
        initial_bankroll: float,
        warning_pct: float = 0.10,
        critical_pct: float = 0.15,
        max_pct: float = 0.20,
        auto_kill_at_max: bool = True,
    ) -> None:
        self.initial_bankroll = initial_bankroll
        self.peak_bankroll = initial_bankroll
        self.warning_pct = warning_pct
        self.critical_pct = critical_pct
        self.max_pct = max_pct
        self.auto_kill_at_max = auto_kill_at_max

        # Daily loss tracking
        self.today: date = date.today()
        self.daily_realized_pnl: float = 0.0

    def update(self, current_bankroll: float, realized_pnl: float = 0.0) -> DrawdownLevel:
        # Reset daily P&L on new day
        today = date.today()
        if today != self.today:
            self.today = today
            self.daily_realized_pnl = 0.0

        self.daily_realized_pnl += realized_pnl

        if current_bankroll > self.peak_bankroll:
            self.peak_bankroll = current_bankroll

        drawdown = self._drawdown_pct(current_bankroll)
        if drawdown >= self.max_pct:
            return "max"
        if drawdown >= self.critical_pct:
            return "critical"
        if drawdown >= self.warning_pct:
            return "warning"
        return "normal"

    def position_multiplier(self, level: DrawdownLevel) -> float:
        return {"normal": 1.0, "warning": 0.5, "critical": 0.25, "max": 0.0}[level]

    def is_trading_halted(self, level: DrawdownLevel) -> bool:
        return level == "max"

    def daily_loss_exceeded(self, max_daily_loss: float) -> bool:
        return self.daily_realized_pnl <= -max_daily_loss

    def _drawdown_pct(self, current_bankroll: float) -> float:
        if self.peak_bankroll <= 0:
            return 0.0
        return max(0.0, (self.peak_bankroll - current_bankroll) / self.peak_bankroll)
