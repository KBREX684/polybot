from __future__ import annotations

from src.polybot.engine.market_classifier import MarketCategory, build_category_queries, classify_market
from src.polybot.retrieval.evidence_store import EvidenceStore
from src.polybot.schemas import EvidenceItem, EvidencePack, GraphEdge, MarketCandidate


class GraphRAG:
    def __init__(self, evidence_store: EvidenceStore, top_k: int = 8) -> None:
        self.evidence_store = evidence_store
        self.top_k = top_k

    def retrieve_for_market(self, market: MarketCandidate, category: MarketCategory | None = None) -> EvidencePack:
        queries = self._build_queries(market, category)
        merged_items: list[EvidenceItem] = []
        merged_edges: list[GraphEdge] = []
        for q in queries:
            pack = self.evidence_store.retrieve(query=q, market=market, top_k=self.top_k)
            merged_items.extend(pack.items)
            merged_edges.extend(pack.edges)

        unique_items: dict[str, EvidenceItem] = {}
        for item in merged_items:
            if item.evidence_id not in unique_items:
                unique_items[item.evidence_id] = item

        final_items = self._rank_items(list(unique_items.values()))[: self.top_k]
        final_edges = merged_edges[: self.top_k]
        contradiction = self._estimate_contradiction(final_edges)
        return EvidencePack(
            query=" || ".join(queries),
            items=final_items,
            edges=final_edges,
            contradiction_score=contradiction,
        )

    def _build_queries(self, market: MarketCandidate, category: MarketCategory | None = None) -> list[str]:
        cat = category or classify_market(market)
        return build_category_queries(market, cat)

    def _rank_items(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        items.sort(key=lambda x: (x.quality_score, x.published_at), reverse=True)
        return items

    def _estimate_contradiction(self, edges: list[GraphEdge]) -> float:
        if not edges:
            return 0.0
        contradictions = sum(1 for e in edges if e.relation == "contradicts" or e.signed_weight < 0)
        return round(contradictions / len(edges), 4)
