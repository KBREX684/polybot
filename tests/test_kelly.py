from src.polybot.risk.kelly import fractional_kelly


def test_fractional_kelly_positive_edge():
    k = fractional_kelly(prob_true=0.62, market_price=0.5, fraction=0.25)
    assert k > 0
    assert k <= 1


def test_fractional_kelly_negative_edge():
    k = fractional_kelly(prob_true=0.45, market_price=0.6, fraction=0.25)
    assert k == 0
