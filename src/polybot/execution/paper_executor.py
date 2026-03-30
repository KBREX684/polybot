from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polybot.schemas import TradeIntent


class PaperExecutor:
    def __init__(self, ledger_path: str) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def execute(self, intent: TradeIntent) -> dict[str, Any]:
        fill_price = intent.limit_price
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "mode": "paper",
            "status": "filled",
            "market_id": intent.market_id,
            "side": intent.side,
            "size_usdc": intent.size_usdc,
            "fill_price": fill_price,
            "reason_code": intent.reason_code,
        }
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
