from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.polybot.config import Settings
from src.polybot.data.data_collector import DataCollector
from src.polybot.data.gamma_client import GammaClient
from src.polybot.data.market_scout import MarketScout
from src.polybot.decision.discriminator import SignalDiscriminator
from src.polybot.decision.generator import SignalGenerator
from src.polybot.execution.paper_executor import PaperExecutor
from src.polybot.filters.hard_filter import HardFilter
from src.polybot.llm.base import LLMAdapter
from src.polybot.llm.mock import MockLLMAdapter
from src.polybot.llm.openai_compatible import OpenAICompatibleAdapter
from src.polybot.observability.decision_logger import DecisionLogger
from src.polybot.retrieval.evidence_store import (
    ChainEvidenceStore,
    MarketMetadataEvidenceStore,
    PostgresGraphEvidenceStore,
)
from src.polybot.retrieval.graph_rag import GraphRAG
from src.polybot.retrieval.serper_news import SerperNewsClient, SerperNewsEvidenceStore
from src.polybot.risk.risk_engine import RiskEngine
from src.polybot.schemas import DecisionRecord, DiscriminatorOutput, GeneratorOutput, RiskDecision, TradeIntent


class TradingPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gamma = GammaClient(base_url=settings.polymarket_gamma_url)
        self.scout = MarketScout(self.gamma)

        evidence_stores = []
        if settings.graph_rag_pg_dsn:
            evidence_stores.append(PostgresGraphEvidenceStore(dsn=settings.graph_rag_pg_dsn))
        if settings.serper_api_key:
            serper_client = SerperNewsClient(
                api_key=settings.serper_api_key,
                endpoint=settings.serper_endpoint,
                gl=settings.serper_gl,
                hl=settings.serper_hl,
                num=settings.serper_num,
            )
            evidence_stores.append(SerperNewsEvidenceStore(client=serper_client))
        evidence_stores.append(MarketMetadataEvidenceStore())

        chain_store = ChainEvidenceStore(stores=evidence_stores)
        graph_rag = GraphRAG(evidence_store=chain_store, top_k=settings.graph_rag_top_k)
        self.collector = DataCollector(graph_rag=graph_rag)

        generator_llm = self._make_generator_llm()
        discriminator_llm = self._make_discriminator_llm()
        self.generator = SignalGenerator(generator_llm, temperature=settings.generator_temperature)
        self.discriminator = SignalDiscriminator(
            discriminator_llm, temperature=max(0.01, settings.discriminator_temperature)
        )

        self.filter = HardFilter(settings=settings)
        self.risk = RiskEngine(settings=settings)
        self.executor = PaperExecutor(ledger_path=settings.paper_ledger_path)
        self.logger = DecisionLogger(log_path=settings.decision_log_path)
        self.bankroll_usdc = settings.default_bankroll_usdc

    def run_once(self, limit: int) -> dict[str, Any]:
        markets = self.scout.fetch_candidates(limit=limit)
        summary = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "markets_scanned": len(markets),
            "hard_filter_passed": 0,
            "generated": 0,
            "reviewed": 0,
            "risk_passed": 0,
            "executed": 0,
            "errors": 0,
        }
        for market in markets:
            filter_result = self.filter.evaluate(market)

            generated = GeneratorOutput(
                market_id=market.market_id,
                side="NO_TRADE",
                fair_prob=market.market_prob,
                market_prob=market.market_prob,
                edge_raw=0.0,
                confidence=0.0,
                reasoning_paths=["filtered_out"],
                key_assumptions=[],
                invalidation_triggers=[],
                evidence_refs=[],
            )
            reviewed = DiscriminatorOutput(
                verdict="reject",
                edge_adjustment=0.0,
                rejected_edges=[],
                logic_flaws=[],
                missing_evidence=[],
                final_edge=0.0,
                final_confidence=0.0,
            )
            risk_decision = RiskDecision(
                passed=False,
                blocked_rules=["not_evaluated"],
                kelly_fraction=0.0,
                suggested_size_usdc=0.0,
                reason="not_evaluated",
            )
            executed_trade: dict[str, Any] | None = None

            try:
                if not filter_result.passed:
                    self._log_record(market, filter_result.passed, filter_result.reasons, generated, reviewed, risk_decision)
                    continue
                summary["hard_filter_passed"] += 1

                evidence = self.collector.collect(market)
                generated = self.generator.generate(market=market, evidence=evidence)
                summary["generated"] += 1

                reviewed = self.discriminator.review(market=market, evidence=evidence, generated=generated)
                summary["reviewed"] += 1

                risk_decision = self.risk.evaluate(
                    market=market,
                    generated=generated,
                    reviewed=reviewed,
                    bankroll_usdc=self.bankroll_usdc,
                )
                if risk_decision.passed:
                    summary["risk_passed"] += 1
                    if generated.side in {"BUY_YES", "BUY_NO"}:
                        intent = TradeIntent(
                            market_id=market.market_id,
                            side=generated.side,
                            limit_price=market.market_prob,
                            size_usdc=risk_decision.suggested_size_usdc,
                            reason_code="generator_discriminator_risk_pass",
                        )
                        executed_trade = self.executor.execute(intent)
                        summary["executed"] += 1
                        self.bankroll_usdc -= risk_decision.suggested_size_usdc

                self._log_record(
                    market,
                    filter_result.passed,
                    filter_result.reasons,
                    generated,
                    reviewed,
                    risk_decision,
                    executed_trade,
                )
            except Exception as exc:
                summary["errors"] += 1
                risk_decision = RiskDecision(
                    passed=False,
                    blocked_rules=["runtime_error"],
                    kelly_fraction=0.0,
                    suggested_size_usdc=0.0,
                    reason=str(exc),
                )
                self._log_record(
                    market,
                    filter_result.passed,
                    filter_result.reasons,
                    generated,
                    reviewed,
                    risk_decision,
                )

        summary["bankroll_after_cycle"] = round(self.bankroll_usdc, 2)
        return summary

    def _log_record(
        self,
        market: Any,
        filter_passed: bool,
        filter_reasons: list[str],
        generated: GeneratorOutput,
        reviewed: DiscriminatorOutput,
        risk_decision: RiskDecision,
        executed_trade: dict[str, Any] | None = None,
    ) -> None:
        record = DecisionRecord(
            market_id=market.market_id,
            question=market.question,
            filter_passed=filter_passed,
            filter_reasons=filter_reasons,
            generator_output=generated.model_dump(mode="json"),
            discriminator_output=reviewed.model_dump(mode="json"),
            risk_decision=risk_decision.model_dump(mode="json"),
            executed_trade=executed_trade,
        )
        self.logger.write(record)

    def _make_generator_llm(self) -> LLMAdapter:
        if self.settings.generator_api_key:
            return OpenAICompatibleAdapter(
                model=self.settings.generator_model,
                api_key=self.settings.generator_api_key,
                base_url=self.settings.generator_base_url,
                force_json_mode=True,
            )
        if self.settings.allow_mock_llm:
            return MockLLMAdapter(role="generator")
        raise ValueError("GENERATOR_API_KEY missing and mock disabled")

    def _make_discriminator_llm(self) -> LLMAdapter:
        if self.settings.discriminator_api_key:
            return OpenAICompatibleAdapter(
                model=self.settings.discriminator_model,
                api_key=self.settings.discriminator_api_key,
                base_url=self.settings.discriminator_base_url,
                force_json_mode=True,
            )
        if self.settings.allow_mock_llm:
            return MockLLMAdapter(role="discriminator")
        raise ValueError("DISCRIMINATOR_API_KEY missing and mock disabled")
