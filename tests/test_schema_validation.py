import pytest
from pydantic import ValidationError

from src.polybot.schemas import DiscriminatorOutput, GeneratorOutput


def test_generator_output_requires_reasoning_paths():
    with pytest.raises(ValidationError):
        GeneratorOutput(
            market_id="1",
            side="BUY_YES",
            fair_prob=0.6,
            market_prob=0.5,
            edge_raw=0.1,
            confidence=0.7,
            reasoning_paths=[],
            key_assumptions=[],
            invalidation_triggers=[],
            evidence_refs=[],
        )


def test_discriminator_output_accepts_valid_payload():
    payload = DiscriminatorOutput(
        verdict="accept",
        edge_adjustment=0.01,
        rejected_edges=[],
        logic_flaws=[],
        missing_evidence=[],
        final_edge=0.04,
        final_confidence=0.72,
    )
    assert payload.verdict == "accept"
