from __future__ import annotations

from src.polybot.retrieval.graph_rag import GraphRAG
from src.polybot.schemas import EvidencePack, MarketCandidate


class DataCollector:
    def __init__(self, graph_rag: GraphRAG) -> None:
        self.graph_rag = graph_rag

    def collect(self, market: MarketCandidate) -> EvidencePack:
        return self.graph_rag.retrieve_for_market(market)
