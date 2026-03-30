from __future__ import annotations

from dataclasses import dataclass

from src.polybot.config import Settings
from src.polybot.schemas import MarketCandidate


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reasons: list[str]


class HardFilter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(self, market: MarketCandidate) -> FilterResult:
        reasons: list[str] = []
        if market.liquidity_usdc < self.settings.min_liquidity_usdc:
            reasons.append("liquidity_below_min")
        if market.spread > self.settings.max_spread:
            reasons.append("spread_above_max")
        if market.hours_to_end < self.settings.min_hours_to_end:
            reasons.append("too_close_to_resolution")
        if market.hours_to_end > self.settings.max_hours_to_end:
            reasons.append("too_far_from_resolution")
        if market.market_prob <= 0.01 or market.market_prob >= 0.99:
            reasons.append("extreme_price_zone")
        return FilterResult(passed=len(reasons) == 0, reasons=reasons)
