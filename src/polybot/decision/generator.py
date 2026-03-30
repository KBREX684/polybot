from __future__ import annotations

import json

from src.polybot.llm.base import LLMAdapter
from src.polybot.schemas import EvidencePack, GeneratorOutput, MarketCandidate


GENERATOR_SYSTEM_PROMPT = """You are the Generator model in a prediction-market trading system.
You must use Graph-of-Thought style reasoning:
1) Produce multiple independent reasoning paths.
2) Stress-test each path with disconfirming evidence.
3) Convert analysis to one trade signal with edge and confidence.

You must output one strict JSON object only.
No markdown, no extra text.
"""


class SignalGenerator:
    def __init__(self, llm: LLMAdapter, temperature: float = 0.2) -> None:
        self.llm = llm
        self.temperature = temperature

    def generate(self, market: MarketCandidate, evidence: EvidencePack) -> GeneratorOutput:
        user_prompt = f"""
Market:
{market.model_dump_json()}

Evidence Pack:
{evidence.model_dump_json()}

Return JSON fields exactly:
{{
  "market_id": "string",
  "side": "BUY_YES | BUY_NO | NO_TRADE",
  "fair_prob": 0..1,
  "market_prob": 0..1,
  "edge_raw": -1..1,
  "confidence": 0..1,
  "reasoning_paths": ["path1", "path2", "path3"],
  "key_assumptions": ["..."],
  "invalidation_triggers": ["..."],
  "evidence_refs": ["evidence_id"]
}}

Rules:
- reasoning_paths must include at least 3 distinct paths
- edge_raw = fair_prob - market_prob when side is BUY_YES
- if signal quality is weak, output NO_TRADE
""".strip()
        payload = self.llm.generate_json(
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=self.temperature,
        )

        # Ensure market id binds to current candidate even if model drifts.
        payload["market_id"] = market.market_id
        if "market_prob" not in payload:
            payload["market_prob"] = market.market_prob

        parsed = GeneratorOutput.model_validate(payload)
        if parsed.side == "BUY_YES":
            parsed.edge_raw = round(parsed.fair_prob - parsed.market_prob, 6)
        elif parsed.side == "BUY_NO":
            parsed.edge_raw = round((1 - parsed.fair_prob) - (1 - parsed.market_prob), 6)
        return parsed
