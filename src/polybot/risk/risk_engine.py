from __future__ import annotations

from src.polybot.config import Settings
from src.polybot.risk.drawdown_tracker import DrawdownTracker
from src.polybot.risk.kelly import fractional_kelly
from src.polybot.schemas import DiscriminatorOutput, DrawdownLevel, GeneratorOutput, MarketCandidate, RiskDecision


class RiskEngine:
    def __init__(self, settings: Settings, drawdown_tracker: DrawdownTracker | None = None) -> None:
        self.settings = settings
        self.drawdown_tracker = drawdown_tracker
        self.max_open_positions: int = 25

    def evaluate(
        self,
        market: MarketCandidate,
        generated: GeneratorOutput,
        reviewed: DiscriminatorOutput,
        bankroll_usdc: float,
        open_position_count: int = 0,
    ) -> RiskDecision:
        blocked: list[str] = []

        # Kill switch check
        if self.settings.kill_switch:
            blocked.append("kill_switch_active")

        # Generator no-trade
        if generated.side == "NO_TRADE":
            blocked.append("generator_no_trade")

        # Discriminator reject
        if reviewed.verdict == "reject":
            blocked.append("discriminator_reject")

        # Net edge check
        if reviewed.final_edge < self.settings.min_net_edge:
            blocked.append("edge_below_min_net_edge")

        # Confidence filter
        if reviewed.final_confidence < 0.55:
            blocked.append("confidence_below_min")

        # Max open positions
        if open_position_count >= self.max_open_positions:
            blocked.append("max_open_positions_reached")

        # Daily loss limit
        if self.drawdown_tracker and self.drawdown_tracker.daily_loss_exceeded(self.settings.max_daily_loss_usdc):
            blocked.append("daily_loss_limit_exceeded")

        # Drawdown heat system
        drawdown_mult = 1.0
        if self.drawdown_tracker:
            level = self.drawdown_tracker.update(bankroll_usdc)
            drawdown_mult = self.drawdown_tracker.position_multiplier(level)
            if self.drawdown_tracker.is_trading_halted(level):
                blocked.append("drawdown_max_halted")
            if level == "critical":
                blocked.append("drawdown_critical_reduced")

        estimated_prob = max(0.001, min(0.999, market.market_prob + reviewed.final_edge))
        kelly = fractional_kelly(
            prob_true=estimated_prob,
            market_price=market.market_prob,
            fraction=self.settings.kelly_fraction,
        )
        multiplier = self._risk_multiplier(
            confidence=reviewed.final_confidence,
            liquidity=market.liquidity_usdc,
            spread=market.spread,
            hours_to_end=market.hours_to_end,
        )
        raw_fraction = kelly * multiplier * drawdown_mult
        capped_fraction = min(raw_fraction, self.settings.max_single_market_allocation)
        suggested_size = bankroll_usdc * capped_fraction

        if suggested_size < self.settings.min_trade_usdc:
            blocked.append("size_below_min_trade")

        if blocked:
            return RiskDecision(
                passed=False,
                blocked_rules=blocked,
                kelly_fraction=round(capped_fraction, 6),
                suggested_size_usdc=0.0,
                reason="blocked_by_risk_rules",
            )

        return RiskDecision(
            passed=True,
            blocked_rules=[],
            kelly_fraction=round(capped_fraction, 6),
            suggested_size_usdc=round(suggested_size, 2),
            reason="risk_pass",
        )

    def _risk_multiplier(
        self,
        confidence: float,
        liquidity: float,
        spread: float,
        hours_to_end: float,
    ) -> float:
        confidence_mult = 0.6 + 0.6 * max(0.0, min(1.0, confidence))
        liquidity_mult = 1.0 if liquidity >= 10000 else 0.8 if liquidity >= 5000 else 0.6
        spread_mult = 1.0 if spread <= 0.02 else 0.8 if spread <= 0.04 else 0.6
        horizon_mult = 1.0 if 48 <= hours_to_end <= 240 else 0.85
        return confidence_mult * liquidity_mult * spread_mult * horizon_mult
