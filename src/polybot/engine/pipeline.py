from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.polybot.config import Settings
from src.polybot.data.data_collector import DataCollector
from src.polybot.data.gamma_client import GammaClient
from src.polybot.data.market_scout import MarketScout
from src.polybot.decision.discriminator import SignalDiscriminator
from src.polybot.decision.generator import SignalGenerator
from src.polybot.engine.market_classifier import classify_market
from src.polybot.execution.paper_executor import PaperExecutor
from src.polybot.execution.position_manager import PositionManager
from src.polybot.filters.hard_filter import HardFilter
from src.polybot.forecast.calibrator import Calibrator
from src.polybot.llm.base import LLMAdapter
from src.polybot.llm.mock import MockLLMAdapter
from src.polybot.llm.openai_compatible import OpenAICompatibleAdapter
from src.polybot.observability.alerts import AlertManager
from src.polybot.retrieval.evidence_store import (
    ChainEvidenceStore,
    MarketMetadataEvidenceStore,
    PostgresGraphEvidenceStore,
)
from src.polybot.retrieval.graph_rag import GraphRAG
from src.polybot.retrieval.serper_news import SerperNewsClient, SerperNewsEvidenceStore
from src.polybot.retrieval.whale_tracker import WhaleTracker
from src.polybot.risk.drawdown_tracker import DrawdownTracker
from src.polybot.risk.risk_engine import RiskEngine
from src.polybot.schemas import (
    DecisionRecord,
    DiscriminatorOutput,
    GeneratorOutput,
    Position,
    RiskDecision,
    TradeIntent,
)
from src.polybot.storage.database import Database


class TradingPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.gamma = GammaClient(
            base_url=settings.polymarket_gamma_url,
            cache_ttl_seconds=settings.gamma_cache_ttl_seconds,
        )
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
                cache_ttl_seconds=settings.serper_cache_ttl_seconds,
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

        # Drawdown tracker
        self.drawdown_tracker = DrawdownTracker(
            initial_bankroll=settings.default_bankroll_usdc,
            warning_pct=settings.warning_drawdown_pct,
            critical_pct=settings.critical_drawdown_pct,
            max_pct=settings.max_drawdown_pct,
            auto_kill_at_max=settings.auto_kill_at_max,
        )
        self.risk = RiskEngine(settings=settings, drawdown_tracker=self.drawdown_tracker)

        self.executor = PaperExecutor(ledger_path=settings.paper_ledger_path)

        # Calibrator
        self.calibrator = Calibrator(
            log_path="logs/calibration.jsonl",
            extreme_threshold=settings.calibration_extreme_threshold,
            evidence_penalty_weight=settings.calibration_evidence_penalty_weight,
            contradiction_penalty_weight=settings.calibration_contradiction_penalty_weight,
            auto_retrain_after=settings.calibration_auto_retrain_after,
        )

        # Position manager
        self.position_manager = PositionManager(
            positions_path="logs/positions.jsonl",
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
            max_hold_hours=settings.max_hold_hours,
        )

        # P2-1: Whale tracker
        self.whale_tracker = WhaleTracker(
            max_wallets=settings.whale_max_wallets,
            min_conviction_score=settings.whale_min_conviction,
            conviction_edge_boost=settings.whale_edge_boost,
            conviction_edge_penalty=settings.whale_edge_penalty,
        ) if settings.whale_enabled else None

        # P2-4: SQLite storage
        self.db = Database(db_path=settings.db_path)

        # P2-3: Alerts
        self.alerts = AlertManager(
            telegram_bot_token=settings.alert_telegram_bot_token,
            telegram_chat_id=settings.alert_telegram_chat_id,
            discord_webhook=settings.alert_discord_webhook,
            slack_webhook=settings.alert_slack_webhook,
            cooldown_seconds=settings.alert_cooldown_seconds,
        )

        self.bankroll_usdc = settings.default_bankroll_usdc

    def run_once(self, limit: int) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "markets_scanned": 0,
            "hard_filter_passed": 0,
            "generated": 0,
            "reviewed": 0,
            "calibrated": 0,
            "risk_passed": 0,
            "executed": 0,
            "positions_closed": 0,
            "errors": 0,
        }

        # Kill switch
        if self.settings.kill_switch:
            summary["skipped"] = True
            summary["reason"] = "kill_switch_active"
            closed = self.position_manager.force_close_all(reason="kill_switch")
            summary["positions_closed"] = len(closed)
            self.alerts.alert_kill_switch()
            self.db.insert_cycle(summary)
            return summary

        # Drawdown check
        drawdown_level = self.drawdown_tracker.update(self.bankroll_usdc)
        summary["drawdown_level"] = drawdown_level
        if self.drawdown_tracker.is_trading_halted(drawdown_level):
            summary["skipped"] = True
            summary["reason"] = "drawdown_max_halted"
            closed = self.position_manager.force_close_all(reason="kill_switch")
            summary["positions_closed"] = len(closed)
            for sig in closed:
                self.bankroll_usdc += sig.pnl_usdc
                self.drawdown_tracker.update(self.bankroll_usdc, realized_pnl=sig.pnl_usdc)
                self.db.close_position(sig.position_id, "kill_switch", sig.pnl_usdc, sig.exit_price)
            self.alerts.alert_kill_switch()
            self.db.insert_cycle(summary)
            return summary

        # Position exits
        current_edges: dict[str, float] = {}
        for pos in self.position_manager.open_positions():
            current_edges[pos.market_id] = 0.0

        exit_signals = self.position_manager.check_exits(current_edge_by_market=current_edges)
        for sig in exit_signals:
            self.bankroll_usdc += sig.pnl_usdc
            self.drawdown_tracker.update(self.bankroll_usdc, realized_pnl=sig.pnl_usdc)
            summary["positions_closed"] += 1
            self.db.close_position(sig.position_id, sig.reason, sig.pnl_usdc, sig.exit_price)
            self.db.insert_trade(
                market_id=sig.position_id, side="CLOSE", size_usdc=abs(sig.pnl_usdc),
                fill_price=sig.exit_price, reason_code=sig.reason,
            )
        summary["exit_signals"] = [
            {"market_id": s.position_id, "reason": s.reason, "pnl": round(s.pnl_usdc, 4)}
            for s in exit_signals
        ]

        # Daily loss
        if self.drawdown_tracker.daily_loss_exceeded(self.settings.max_daily_loss_usdc):
            summary["skipped"] = True
            summary["reason"] = "daily_loss_limit_exceeded"
            self.alerts.alert_daily_loss(
                loss_usdc=abs(self.drawdown_tracker.daily_realized_pnl),
                limit_usdc=self.settings.max_daily_loss_usdc,
            )
            self.db.insert_cycle(summary)
            return summary

        # Main pipeline
        markets = self.scout.fetch_candidates(limit=limit)
        summary["markets_scanned"] = len(markets)
        cycle_edges: dict[str, float] = {}

        # P2-1: Whale scan
        whale_signals = {}
        if self.whale_tracker and self.settings.whale_enabled:
            market_ids = [m.market_id for m in markets]
            whale_signals = self.whale_tracker.scan_markets(market_ids)
            for mid, ws in whale_signals.items():
                self.db.upsert_whale_score(
                    mid, ws.whale_count_yes, ws.whale_count_no,
                    ws.total_whales, ws.conviction, ws.edge_boost,
                )

        for market in markets:
            category = classify_market(market)

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
            calibrated_prob: float | None = None

            try:
                if not filter_result.passed:
                    self._record(market, filter_result, generated, reviewed,
                                 risk_decision, category=category, whale_signal=whale_signals.get(market.market_id))
                    continue
                summary["hard_filter_passed"] += 1

                evidence = self.collector.collect(market)
                generated = self.generator.generate(market=market, evidence=evidence)
                summary["generated"] += 1

                reviewed = self.discriminator.review(market=market, evidence=evidence, generated=generated)
                summary["reviewed"] += 1

                # Calibrate
                calibrated_prob = self.calibrator.calibrate(
                    raw_prob=generated.fair_prob,
                    evidence=evidence,
                    discriminator_edge=reviewed.edge_adjustment,
                    category=category,
                    market_id=market.market_id,
                )
                summary["calibrated"] += 1
                generated.fair_prob = calibrated_prob
                if generated.side == "BUY_YES":
                    generated.edge_raw = round(calibrated_prob - generated.market_prob, 6)
                elif generated.side == "BUY_NO":
                    generated.edge_raw = round((1 - calibrated_prob) - (1 - generated.market_prob), 6)

                # P2-1: Apply whale edge boost/penalty
                whale_edge = 0.0
                ws = whale_signals.get(market.market_id)
                if ws and ws.conviction >= self.settings.whale_min_conviction:
                    # Check if whale consensus aligns with our signal
                    if (generated.side == "BUY_YES" and ws.whale_count_yes > ws.whale_count_no) or \
                       (generated.side == "BUY_NO" and ws.whale_count_no > ws.whale_count_yes):
                        whale_edge = ws.edge_boost
                    else:
                        whale_edge = -self.settings.whale_edge_penalty
                    reviewed.final_edge = round(reviewed.final_edge + whale_edge, 6)

                cycle_edges[market.market_id] = reviewed.final_edge

                risk_decision = self.risk.evaluate(
                    market=market,
                    generated=generated,
                    reviewed=reviewed,
                    bankroll_usdc=self.bankroll_usdc,
                    open_position_count=self.position_manager.open_position_count(),
                )
                if risk_decision.passed:
                    summary["risk_passed"] += 1
                    if generated.side in {"BUY_YES", "BUY_NO"}:
                        if self.position_manager.get_open_position(market.market_id):
                            risk_decision = RiskDecision(
                                passed=False,
                                blocked_rules=["already_positioned"],
                                kelly_fraction=0.0,
                                suggested_size_usdc=0.0,
                                reason="already_positioned",
                            )
                        else:
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

                            position = Position(
                                market_id=market.market_id,
                                question=market.question,
                                side=generated.side,
                                entry_price=market.market_prob,
                                current_price=market.market_prob,
                                size_usdc=risk_decision.suggested_size_usdc,
                                opened_at=datetime.now(tz=timezone.utc),
                                stop_loss_price=self._calc_stop_loss(generated.side, market.market_prob),
                                take_profit_price=self._calc_take_profit(generated.side, market.market_prob),
                                max_hold_hours=self.settings.max_hold_hours,
                                category=category,
                            )
                            self.position_manager.open_position(position)

                            # DB records
                            self.db.insert_trade(
                                market_id=market.market_id,
                                side=generated.side,
                                size_usdc=risk_decision.suggested_size_usdc,
                                fill_price=market.market_prob,
                                reason_code="generator_discriminator_risk_pass",
                            )
                            self.db.open_position(
                                market_id=market.market_id,
                                question=market.question,
                                side=generated.side,
                                entry_price=market.market_prob,
                                size_usdc=risk_decision.suggested_size_usdc,
                                opened_at=datetime.now(tz=timezone.utc).isoformat(),
                                stop_loss=position.stop_loss_price,
                                take_profit=position.take_profit_price,
                                max_hold_hours=position.max_hold_hours,
                                category=category,
                            )

                            # Alert
                            self.alerts.alert_trade_executed(
                                market_id=market.market_id,
                                side=generated.side,
                                size_usdc=risk_decision.suggested_size_usdc,
                                edge=reviewed.final_edge,
                            )

                            # Calibration record
                            self.db.insert_calibration(
                                market_id=market.market_id,
                                category=category,
                                raw_prob=generated.fair_prob,
                                calibrated_prob=calibrated_prob,
                            )

                self._record(market, filter_result, generated, reviewed,
                             risk_decision, executed_trade, category=category,
                             calibrated_prob=calibrated_prob, whale_signal=ws)

            except Exception as exc:
                summary["errors"] += 1
                risk_decision = RiskDecision(
                    passed=False,
                    blocked_rules=["runtime_error"],
                    kelly_fraction=0.0,
                    suggested_size_usdc=0.0,
                    reason=str(exc),
                )
                self._record(market, filter_result, generated, reviewed,
                             risk_decision, category=category, calibrated_prob=calibrated_prob)

        # Re-check exits
        post_exits = self.position_manager.check_exits(current_edge_by_market=cycle_edges)
        for sig in post_exits:
            self.bankroll_usdc += sig.pnl_usdc
            self.drawdown_tracker.update(self.bankroll_usdc, realized_pnl=sig.pnl_usdc)
            summary["positions_closed"] += 1
            self.db.close_position(sig.position_id, sig.reason, sig.pnl_usdc, sig.exit_price)

        summary["bankroll_after_cycle"] = round(self.bankroll_usdc, 2)
        summary["drawdown_level_final"] = self.drawdown_tracker.update(self.bankroll_usdc)
        summary["open_positions"] = self.position_manager.open_position_count()
        summary["avg_brier_score"] = self.calibrator.average_brier()
        summary["whale_smi"] = self.whale_tracker.smart_money_index() if self.whale_tracker else None

        # Save cycle to DB
        self.db.insert_cycle(summary)

        # Cycle summary alert
        self.alerts.alert_cycle_summary({
            "scanned": summary["markets_scanned"],
            "executed": summary["executed"],
            "errors": summary["errors"],
            "bankroll": summary["bankroll_after_cycle"],
            "drawdown": summary["drawdown_level_final"],
        })

        return summary

    def _record(
        self,
        market: Any,
        filter_result: Any,
        generated: GeneratorOutput,
        reviewed: DiscriminatorOutput,
        risk_decision: RiskDecision,
        executed_trade: dict | None = None,
        category: str | None = None,
        calibrated_prob: float | None = None,
        whale_signal: Any = None,
    ) -> None:
        extra: dict[str, Any] = {}
        if category:
            extra["category"] = category
        if calibrated_prob is not None:
            extra["calibrated_prob"] = calibrated_prob
        if whale_signal:
            extra["whale"] = whale_signal.to_dict()

        # Write to SQLite
        self.db.insert_decision(
            market_id=market.market_id,
            question=market.question,
            filter_passed=filter_result.passed,
            filter_reasons=filter_result.reasons,
            generator_output=generated.model_dump(mode="json"),
            discriminator_output=reviewed.model_dump(mode="json"),
            risk_decision=risk_decision.model_dump(mode="json"),
            executed_trade=executed_trade,
            category=category,
            calibrated_prob=calibrated_prob,
        )

    def _calc_stop_loss(self, side: str, entry_price: float) -> float:
        if side == "BUY_YES":
            return round(max(0.01, entry_price * (1 - self.settings.stop_loss_pct)), 4)
        return round(min(0.99, entry_price * (1 + self.settings.stop_loss_pct)), 4)

    def _calc_take_profit(self, side: str, entry_price: float) -> float:
        if side == "BUY_YES":
            return round(min(0.99, entry_price * (1 + self.settings.take_profit_pct)), 4)
        return round(max(0.01, entry_price * (1 - self.settings.take_profit_pct)), 4)

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
