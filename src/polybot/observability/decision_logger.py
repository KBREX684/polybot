from __future__ import annotations

import json
from pathlib import Path

from src.polybot.schemas import DecisionRecord


class DecisionLogger:
    def __init__(self, log_path: str) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: DecisionRecord) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
