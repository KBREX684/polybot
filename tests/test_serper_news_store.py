from src.polybot.retrieval.serper_news import SerperNewsClient, SerperNewsEvidenceStore
from src.polybot.schemas import MarketCandidate
from datetime import datetime, timedelta, timezone


class _FakeSerperClient(SerperNewsClient):
    def __init__(self) -> None:
        pass

    def search_news(self, query: str, num: int):
        return [
            {
                "title": "Regulator may approve proposal this week",
                "snippet": "Analysts expect approval odds to rise sharply.",
                "link": "https://reuters.com/world/test-1",
                "source": "reuters.com",
                "date": "2026-03-30T10:00:00+00:00",
            },
            {
                "title": "Officials could reject proposal after review",
                "snippet": "Sources suggest the motion may fail.",
                "link": "https://apnews.com/article/test-2",
                "source": "apnews.com",
                "date": "2026-03-30T11:00:00+00:00",
            },
        ]

    def fetch_article_text(self, link: str, max_paragraphs: int = 8) -> str:
        if "reuters" in link:
            return "Official agency note says approval could rise after review and pass with support."
        return "Officials indicate reject path may dominate after late block and weak sponsor count."


def test_serper_store_returns_items_and_edges():
    market = MarketCandidate(
        market_id="m1",
        question="Will proposal be approved?",
        market_prob=0.52,
        liquidity_usdc=12000,
        spread=0.02,
        end_time=datetime.now(tz=timezone.utc) + timedelta(hours=72),
        outcomes=["Yes", "No"],
    )
    store = SerperNewsEvidenceStore(client=_FakeSerperClient())
    pack = store.retrieve(query=market.question, market=market, top_k=8)
    assert len(pack.items) == 2
    assert pack.items[0].source.startswith("serper:")
    assert "stance:" in pack.items[0].text
    assert pack.contradiction_score >= 0.0
