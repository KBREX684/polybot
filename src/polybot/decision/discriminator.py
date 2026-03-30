from __future__ import annotations

from src.polybot.llm.base import LLMAdapter
from src.polybot.schemas import DiscriminatorOutput, EvidencePack, GeneratorOutput, MarketCandidate


DISCRIMINATOR_SYSTEM_PROMPT = """You are the Discriminator model in a prediction-market trading system.
Your primary goal is to reject unreasonable or low-quality edge claims.

You must actively find flaws:
- logical contradictions
- timeline mismatch
- weak or stale evidence
- circular reasoning
- overfitting to single source

Output one strict JSON object only.
No markdown, no extra text.
"""


class SignalDiscriminator:
    def __init__(self, llm: LLMAdapter, temperature: float = 0.01) -> None:
        self.llm = llm
        self.temperature = temperature

    def review(
        self,
        market: MarketCandidate,
        evidence: EvidencePack,
        generated: GeneratorOutput,
    ) -> DiscriminatorOutput:
        user_prompt = f"""
Market:
{market.model_dump_json()}

Generator Output:
{generated.model_dump_json()}

Evidence Pack:
{evidence.model_dump_json()}

Return JSON fields exactly:
{{
  "verdict": "accept | reject | revise",
  "edge_adjustment": -1..1,
  "rejected_edges": ["..."],
  "logic_flaws": ["..."],
  "missing_evidence": ["..."],
  "final_edge": -1..1,
  "final_confidence": 0..1
}}

Rules:
- If logical flaws are material, use verdict=reject
- If evidence is incomplete but salvageable, verdict=revise
- final_edge should reflect edge_adjustment from generator edge
- Keep final_confidence conservative when contradiction_score is high
""".strip()
        try:
            payload = self.llm.generate_json(
                system_prompt=DISCRIMINATOR_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self.temperature,
            )

            if "final_edge" not in payload:
                payload["final_edge"] = generated.edge_raw
            if "final_confidence" not in payload:
                payload["final_confidence"] = generated.confidence

            parsed = DiscriminatorOutput.model_validate(payload)
            if parsed.verdict in {"accept", "revise"}:
                parsed.final_edge = round(generated.edge_raw + parsed.edge_adjustment, 6)
            return parsed
        except Exception as exc:
            # Safety fallback: degrade confidence/edge but keep pipeline alive.
            return DiscriminatorOutput(
                verdict="revise",
                edge_adjustment=-0.02,
                rejected_edges=[],
                logic_flaws=[f"llm_parse_failure:{type(exc).__name__}"],
                missing_evidence=["discriminator_json_parse_failed"],
                final_edge=round(max(-1.0, generated.edge_raw - 0.02), 6),
                final_confidence=round(max(0.0, generated.confidence - 0.1), 6),
            )
