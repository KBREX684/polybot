from datetime import datetime, timedelta, timezone

from src.polybot.decision.discriminator import SignalDiscriminator
from src.polybot.llm.base import LLMAdapter
from src.polybot.schemas import EvidencePack, GeneratorOutput, MarketCandidate


class _BrokenLLM(LLMAdapter):
    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int = 1200):
        raise ValueError("boom")


def test_discriminator_fallback_on_parse_failure():
    discriminator = SignalDiscriminator(llm=_BrokenLLM(), temperature=0.01)
    market = MarketCandidate(
        market_id="m1",
        question="Will X happen?",
        market_prob=0.4,
        liquidity_usdc=10000,
        spread=0.02,
        end_time=datetime.now(tz=timezone.utc) + timedelta(hours=72),
        outcomes=["Yes", "No"],
    )
    generated = GeneratorOutput(
        market_id="m1",
        side="BUY_YES",
        fair_prob=0.55,
        market_prob=0.4,
        edge_raw=0.15,
        confidence=0.7,
        reasoning_paths=["p1", "p2", "p3"],
        key_assumptions=[],
        invalidation_triggers=[],
        evidence_refs=[],
    )
    reviewed = discriminator.review(market=market, evidence=EvidencePack(query="q"), generated=generated)
    assert reviewed.verdict == "revise"
    assert reviewed.final_confidence < generated.confidence
