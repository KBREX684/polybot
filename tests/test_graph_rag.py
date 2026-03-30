from datetime import datetime, timedelta, timezone

from src.polybot.retrieval.graph_rag import GraphRAG
from src.polybot.retrieval.evidence_store import EvidenceStore
from src.polybot.schemas import EvidenceItem, EvidencePack, MarketCandidate


class _FakeStore(EvidenceStore):
    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        now = datetime.now(tz=timezone.utc)
        item = EvidenceItem(
            evidence_id=f"id-{abs(hash(query)) % 2}",  # force dedupe collisions
            source="test",
            published_at=now - timedelta(hours=1),
            text=query,
            quality_score=0.8,
        )
        return EvidencePack(query=query, items=[item], edges=[], contradiction_score=0.0)


def test_graph_rag_multi_query_dedup():
    rag = GraphRAG(evidence_store=_FakeStore(), top_k=8)
    market = MarketCandidate(
        market_id="m2",
        question="Will X happen?",
        market_prob=0.5,
        liquidity_usdc=10000,
        spread=0.02,
        end_time=datetime.now(tz=timezone.utc) + timedelta(hours=100),
        outcomes=["Yes", "No"],
    )
    pack = rag.retrieve_for_market(market)
    assert len(pack.items) <= 2
    assert "official confirmation" in pack.query
