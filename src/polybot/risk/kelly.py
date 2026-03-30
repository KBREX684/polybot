from __future__ import annotations


def fractional_kelly(prob_true: float, market_price: float, fraction: float = 0.25) -> float:
    """
    Binary market Kelly sizing.
    market_price in (0,1): YES share cost.
    If outcome occurs, profit multiple b = (1-price)/price.
    """
    if market_price <= 0.0 or market_price >= 1.0:
        return 0.0
    if prob_true <= 0.0 or prob_true >= 1.0:
        prob_true = min(0.999, max(0.001, prob_true))

    b = (1.0 - market_price) / market_price
    q = 1.0 - prob_true
    full_kelly = (b * prob_true - q) / b
    sized = max(0.0, full_kelly) * max(0.0, min(1.0, fraction))
    return max(0.0, min(1.0, sized))
