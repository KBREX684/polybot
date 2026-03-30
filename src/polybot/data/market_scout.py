from __future__ import annotations

from src.polybot.data.gamma_client import GammaClient
from src.polybot.schemas import MarketCandidate


class MarketScout:
    def __init__(self, gamma_client: GammaClient) -> None:
        self.gamma_client = gamma_client

    def fetch_candidates(self, limit: int) -> list[MarketCandidate]:
        raw_markets = self.gamma_client.get_markets(limit=limit, active_only=True)
        candidates: list[MarketCandidate] = []
        for raw in raw_markets:
            candidate = self.gamma_client.to_candidate(raw)
            if candidate and candidate.question:
                candidates.append(candidate)
        return candidates
