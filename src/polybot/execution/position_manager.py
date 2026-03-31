from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polybot.schemas import ExitSignal, MarketCategory, Position


class PositionManager:
    def __init__(
        self,
        positions_path: str = "logs/positions.jsonl",
        stop_loss_pct: float = 0.20,
        take_profit_pct: float = 0.30,
        max_hold_hours: float = 336.0,
        edge_reversal_threshold: float = 0.02,
    ) -> None:
        self.positions_path = Path(positions_path)
        self.positions_path.parent.mkdir(parents=True, exist_ok=True)
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_hours = max_hold_hours
        self.edge_reversal_threshold = edge_reversal_threshold
        self._positions: dict[str, Position] = {}
        self._load_positions()

    def open_position(self, position: Position) -> None:
        self._positions[position.market_id] = position
        self._persist(position)

    def close_position(self, market_id: str, exit_price: float, reason: str) -> ExitSignal | None:
        pos = self._positions.pop(market_id, None)
        if pos is None:
            return None
        pos.current_price = exit_price
        pnl = pos.pnl_usdc
        signal = ExitSignal(
            position_id=market_id,
            reason=reason,  # type: ignore[arg-type]
            exit_price=exit_price,
            pnl_usdc=round(pnl, 4),
        )
        self._remove_persisted(market_id)
        return signal

    def get_open_position(self, market_id: str) -> Position | None:
        return self._positions.get(market_id)

    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def update_prices(self, prices: dict[str, float]) -> None:
        for mid, price in prices.items():
            pos = self._positions.get(mid)
            if pos:
                pos.current_price = price

    def check_exits(
        self,
        current_edge_by_market: dict[str, float] | None = None,
    ) -> list[ExitSignal]:
        """Check all open positions for exit signals. Priority: stop_loss > take_profit > time > edge_reversal."""
        exits: list[ExitSignal] = []
        to_close: list[tuple[str, str, float]] = []

        for mid, pos in list(self._positions.items()):
            # 1. Stop loss check
            loss_pct = self._unrealized_loss_pct(pos)
            if loss_pct >= self.stop_loss_pct:
                to_close.append((mid, "stop_loss", pos.current_price))
                continue

            # 2. Take profit check
            gain_pct = self._unrealized_gain_pct(pos)
            if gain_pct >= self.take_profit_pct:
                to_close.append((mid, "take_profit", pos.current_price))
                continue

            # 3. Time exit — use PM's configured max_hold_hours
            hours_held = (datetime.now(tz=timezone.utc) - pos.opened_at).total_seconds() / 3600.0
            if hours_held >= self.max_hold_hours:
                to_close.append((mid, "time_exit", pos.current_price))
                continue

            # 4. Edge reversal detection
            if current_edge_by_market:
                edge = current_edge_by_market.get(mid, 0.0)
                if self._is_edge_reversed(pos, edge):
                    to_close.append((mid, "edge_reversal", pos.current_price))

        for mid, reason, price in to_close:
            signal = self.close_position(mid, price, reason)
            if signal:
                exits.append(signal)

        return exits

    def force_close_all(self, reason: str = "kill_switch") -> list[ExitSignal]:
        """Emergency close all positions."""
        exits: list[ExitSignal] = []
        for mid in list(self._positions.keys()):
            pos = self._positions.get(mid)
            if pos:
                signal = self.close_position(mid, pos.current_price, reason)
                if signal:
                    exits.append(signal)
        return exits

    def total_unrealized_pnl(self) -> float:
        return sum(p.pnl_usdc for p in self._positions.values())

    def open_position_count(self) -> int:
        return len(self._positions)

    def _unrealized_loss_pct(self, pos: Position) -> float:
        if pos.entry_price <= 0 or pos.size_usdc <= 0:
            return 0.0
        if pos.side == "BUY_YES":
            return max(0.0, (pos.entry_price - pos.current_price) / pos.entry_price)
        return max(0.0, (pos.current_price - pos.entry_price) / pos.entry_price)

    def _unrealized_gain_pct(self, pos: Position) -> float:
        if pos.entry_price <= 0 or pos.size_usdc <= 0:
            return 0.0
        if pos.side == "BUY_YES":
            return max(0.0, (pos.current_price - pos.entry_price) / pos.entry_price)
        return max(0.0, (pos.entry_price - pos.current_price) / pos.entry_price)

    def _is_edge_reversed(self, pos: Position, current_edge: float) -> bool:
        """Edge reversal: if we bought YES and edge is now negative, or vice versa."""
        thresh = self.edge_reversal_threshold
        if pos.side == "BUY_YES" and current_edge < -thresh:
            return True
        if pos.side == "BUY_NO" and current_edge > thresh:
            return True
        return False

    def _persist(self, position: Position) -> None:
        with self.positions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(position.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _remove_persisted(self, market_id: str) -> None:
        if not self.positions_path.exists():
            return
        lines: list[str] = []
        with self.positions_path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    if data.get("market_id") != market_id:
                        lines.append(line.strip())
                except Exception:
                    lines.append(line.strip())
        with self.positions_path.open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    def _load_positions(self) -> None:
        if not self.positions_path.exists():
            return
        with self.positions_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    pos = Position.model_validate(data)
                    if pos.market_id not in self._positions:
                        self._positions[pos.market_id] = pos
                except Exception:
                    continue
