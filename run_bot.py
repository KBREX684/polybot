from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from src.polybot.config import Settings
from src.polybot.engine.pipeline import TradingPipeline
from src.polybot.observability.cycle_logger import CycleLogger


def main() -> None:
    parser = argparse.ArgumentParser(description="Polybot v2 runner")
    parser.add_argument("--limit", type=int, default=None, help="max markets per cycle")
    parser.add_argument("--loop", action="store_true", help="run fixed interval loop")
    parser.add_argument("--cycles", type=int, default=0, help="optional loop count limit (0=unlimited)")
    parser.add_argument("--interval", type=int, default=None, help="override cycle interval seconds")
    args = parser.parse_args()

    settings = Settings.from_env()
    pipeline = TradingPipeline(settings=settings)
    cycle_logger = CycleLogger(settings.cycle_log_path)
    limit = args.limit or settings.max_markets_per_cycle
    interval = args.interval or settings.cycle_interval_seconds

    if not args.loop:
        summary = pipeline.run_once(limit=limit)
        cycle_logger.write(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    n = 0
    while True:
        started = datetime.now(tz=timezone.utc).isoformat()
        summary = pipeline.run_once(limit=limit)
        summary["cycle_started_at"] = started
        summary["cycle_interval_seconds"] = interval
        cycle_logger.write(summary)
        print(json.dumps(summary, ensure_ascii=False))

        n += 1
        if args.cycles > 0 and n >= args.cycles:
            break
        time.sleep(max(1, interval))


if __name__ == "__main__":
    main()
