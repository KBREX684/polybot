from __future__ import annotations

from hashlib import sha256
from typing import Any

from src.polybot.llm.base import LLMAdapter


class MockLLMAdapter(LLMAdapter):
    def __init__(self, role: str) -> None:
        self.role = role

    def _seed(self, text: str) -> float:
        digest = sha256(text.encode("utf-8")).hexdigest()
        return (int(digest[:8], 16) % 1000) / 1000.0

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        seed = self._seed(system_prompt + user_prompt)
        if self.role == "generator":
            fair_prob = min(0.9, max(0.1, 0.45 + 0.2 * (seed - 0.5)))
            market_prob = min(0.9, max(0.1, 0.4 + 0.1 * (0.5 - seed)))
            edge_raw = fair_prob - market_prob
            return {
                "market_id": "mock-market",
                "side": "BUY_YES" if edge_raw > 0.01 else "NO_TRADE",
                "fair_prob": round(fair_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge_raw": round(edge_raw, 4),
                "confidence": round(0.55 + 0.3 * seed, 4),
                "reasoning_paths": [
                    "Base-rate path",
                    "Catalyst path",
                    "Disconfirming path",
                ],
                "key_assumptions": ["Source recency holds"],
                "invalidation_triggers": ["Major contradictory official announcement"],
                "evidence_refs": ["mock-evidence-1"],
            }

        verdict = "accept" if seed > 0.2 else "reject"
        edge_adj = -0.01 if seed < 0.5 else 0.005
        return {
            "verdict": verdict,
            "edge_adjustment": round(edge_adj, 4),
            "rejected_edges": [] if verdict != "reject" else ["Overfit to stale source"],
            "logic_flaws": [] if verdict != "reject" else ["Timeline mismatch"],
            "missing_evidence": [] if seed > 0.4 else ["Need recent primary source"],
            "final_edge": round(0.05 + edge_adj, 4),
            "final_confidence": round(0.6 + 0.2 * seed, 4),
        }
