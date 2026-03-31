from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from src.polybot.data.cache import TTLCache
from src.polybot.schemas import MarketCandidate


class GammaClient:
    def __init__(self, base_url: str, cache_ttl_seconds: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polybot-v2"})
        self.cache = TTLCache(default_ttl_seconds=cache_ttl_seconds)

    def get_markets(self, limit: int = 50, active_only: bool = True) -> list[dict[str, Any]]:
        cache_key = f"markets:{limit}:{active_only}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "limit": limit,
            "active": str(active_only).lower(),
            "closed": "false",
            "archived": "false",
        }
        resp = self.session.get(f"{self.base_url}/markets", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        result = data if isinstance(data, list) else []
        self.cache.set(cache_key, result)
        return result

    def to_candidate(self, raw: dict[str, Any]) -> MarketCandidate | None:
        try:
            outcome_prices = raw.get("outcomePrices", [0.5, 0.5])
            if isinstance(outcome_prices, str):
                import json

                outcome_prices = json.loads(outcome_prices)
            market_prob = float(outcome_prices[0]) if outcome_prices else 0.5

            end_text = raw.get("endDate")
            end_time = datetime.fromisoformat(end_text.replace("Z", "+00:00")) if end_text else datetime.now(
                tz=timezone.utc
            )

            outcomes = raw.get("outcomes", [])
            if isinstance(outcomes, str):
                import json

                outcomes = json.loads(outcomes)

            return MarketCandidate(
                market_id=str(raw.get("id", "")),
                question=str(raw.get("question", "")).strip(),
                market_prob=max(0.0, min(1.0, market_prob)),
                liquidity_usdc=float(raw.get("liquidity", 0.0) or 0.0),
                spread=float(raw.get("spread", 1.0) or 1.0),
                end_time=end_time,
                outcomes=[str(x) for x in outcomes],
            )
        except Exception:
            return None
