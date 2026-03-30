from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import psycopg

from src.polybot.schemas import EvidenceItem, EvidencePack, GraphEdge, MarketCandidate


class EvidenceStore(ABC):
    @abstractmethod
    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        raise NotImplementedError


class PostgresGraphEvidenceStore(EvidenceStore):
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn.strip()
        self._conn: psycopg.Connection[Any] | None = None
        if self.dsn:
            try:
                self._conn = psycopg.connect(self.dsn, autocommit=True)
            except Exception:
                self._conn = None

    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        if self._conn is None:
            return EvidencePack(query=query, items=[], edges=[], contradiction_score=0.0)
        try:
            items = self._load_items(market.market_id, top_k)
            edges = self._load_edges(market.market_id, top_k)
            contradiction = self._estimate_contradiction(edges)
            if not items:
                return EvidencePack(query=query, items=[], edges=[], contradiction_score=0.0)
            return EvidencePack(query=query, items=items, edges=edges, contradiction_score=contradiction)
        except Exception:
            return EvidencePack(query=query, items=[], edges=[], contradiction_score=0.0)

    def _load_items(self, market_id: str, top_k: int) -> list[EvidenceItem]:
        assert self._conn is not None
        sql = """
        SELECT id, source, published_at, chunk_text, quality_score
        FROM doc_chunks
        WHERE market_id = %s
        ORDER BY published_at DESC
        LIMIT %s
        """
        rows = self._conn.execute(sql, (market_id, top_k)).fetchall()
        items: list[EvidenceItem] = []
        for row in rows:
            items.append(
                EvidenceItem(
                    evidence_id=str(row[0]),
                    source=str(row[1]),
                    published_at=row[2],
                    text=str(row[3]),
                    quality_score=float(row[4]),
                )
            )
        return items

    def _load_edges(self, market_id: str, top_k: int) -> list[GraphEdge]:
        assert self._conn is not None
        sql = """
        SELECT from_id, to_id, relation, signed_weight
        FROM edges
        WHERE market_id = %s
        ORDER BY ABS(signed_weight) DESC
        LIMIT %s
        """
        rows = self._conn.execute(sql, (market_id, top_k)).fetchall()
        edges: list[GraphEdge] = []
        for row in rows:
            relation = str(row[2])
            if relation not in {"supports", "contradicts", "causes", "time_precedes", "depends_on"}:
                continue
            edges.append(
                GraphEdge(
                    from_id=str(row[0]),
                    to_id=str(row[1]),
                    relation=relation,  # type: ignore[arg-type]
                    signed_weight=float(row[3]),
                )
            )
        return edges

    def _estimate_contradiction(self, edges: list[GraphEdge]) -> float:
        if not edges:
            return 0.0
        contradictions = sum(1 for e in edges if e.relation == "contradicts" or e.signed_weight < 0)
        return round(contradictions / len(edges), 4)


class MarketMetadataEvidenceStore(EvidenceStore):
    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        item = EvidenceItem(
            evidence_id=f"fallback-{market.market_id}",
            source="fallback:market_metadata",
            published_at=datetime.now(tz=timezone.utc),
            text=f"Question: {market.question}. Market probability={market.market_prob:.3f}.",
            quality_score=0.5,
        )
        return EvidencePack(query=query, items=[item], edges=[], contradiction_score=0.0)


class ChainEvidenceStore(EvidenceStore):
    """
    Merge evidence from multiple stores (e.g., Postgres graph + Serper news + metadata fallback).
    """

    def __init__(self, stores: list[EvidenceStore]) -> None:
        self.stores = stores

    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        merged_items: list[EvidenceItem] = []
        merged_edges: list[GraphEdge] = []
        for store in self.stores:
            pack = store.retrieve(query=query, market=market, top_k=top_k)
            merged_items.extend(pack.items)
            merged_edges.extend(pack.edges)

        # De-duplicate by evidence id while preserving order.
        dedup: dict[str, EvidenceItem] = {}
        for item in merged_items:
            if item.evidence_id not in dedup:
                dedup[item.evidence_id] = item

        final_items = list(dedup.values())[:top_k]
        final_edges = merged_edges[:top_k]
        contradiction = self._estimate_contradiction(final_edges)
        return EvidencePack(
            query=query,
            items=final_items,
            edges=final_edges,
            contradiction_score=contradiction,
        )

    def _estimate_contradiction(self, edges: list[GraphEdge]) -> float:
        if not edges:
            return 0.0
        contradictions = sum(1 for e in edges if e.relation == "contradicts" or e.signed_weight < 0)
        return round(contradictions / len(edges), 4)
