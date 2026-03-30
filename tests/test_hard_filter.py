from datetime import datetime, timedelta, timezone

from src.polybot.config import Settings
from src.polybot.filters.hard_filter import HardFilter
from src.polybot.schemas import MarketCandidate


def _settings() -> Settings:
    return Settings.from_env()


def test_hard_filter_pass_case():
    s = _settings()
    f = HardFilter(s)
    market = MarketCandidate(
        market_id="1",
        question="Will X happen?",
        market_prob=0.55,
        liquidity_usdc=s.min_liquidity_usdc + 1000,
        spread=s.max_spread - 0.01,
        end_time=datetime.now(tz=timezone.utc) + timedelta(hours=72),
        outcomes=["Yes", "No"],
    )
    result = f.evaluate(market)
    assert result.passed is True


def test_hard_filter_blocks_low_liquidity():
    s = _settings()
    f = HardFilter(s)
    market = MarketCandidate(
        market_id="1",
        question="Will X happen?",
        market_prob=0.55,
        liquidity_usdc=s.min_liquidity_usdc - 1,
        spread=s.max_spread - 0.01,
        end_time=datetime.now(tz=timezone.utc) + timedelta(hours=72),
        outcomes=["Yes", "No"],
    )
    result = f.evaluate(market)
    assert result.passed is False
    assert "liquidity_below_min" in result.reasons
