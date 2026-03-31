from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    polymarket_gamma_url: str

    generator_model: str
    generator_api_key: str
    generator_base_url: str
    generator_temperature: float

    discriminator_model: str
    discriminator_api_key: str
    discriminator_base_url: str
    discriminator_temperature: float

    allow_mock_llm: bool
    default_bankroll_usdc: float
    max_markets_per_cycle: int
    paper_ledger_path: str
    decision_log_path: str
    cycle_log_path: str

    graph_rag_pg_dsn: str
    graph_rag_top_k: int
    serper_api_key: str
    serper_endpoint: str
    serper_gl: str
    serper_hl: str
    serper_num: int

    min_liquidity_usdc: float
    max_spread: float
    min_hours_to_end: float
    max_hours_to_end: float

    # Risk
    min_net_edge: float
    max_single_market_allocation: float
    min_trade_usdc: float
    kelly_fraction: float

    # Kill switch
    kill_switch: bool

    # Drawdown heat system
    max_drawdown_pct: float
    warning_drawdown_pct: float
    critical_drawdown_pct: float
    auto_kill_at_max: bool

    # Daily loss limit
    max_daily_loss_usdc: float

    # Position management
    stop_loss_pct: float
    take_profit_pct: float
    max_hold_hours: float

    # Calibration
    calibration_extreme_threshold: float
    calibration_evidence_penalty_weight: float
    calibration_contradiction_penalty_weight: float
    calibration_auto_retrain_after: int

    # Cache
    gamma_cache_ttl_seconds: int
    serper_cache_ttl_seconds: int

    # Dashboard
    dashboard_host: str
    dashboard_port: int
    dashboard_api_key: str
    cycle_interval_seconds: int
    recommended_cycle_interval_seconds: int

    # Whale tracker
    whale_enabled: bool
    whale_max_wallets: int
    whale_min_conviction: float
    whale_edge_boost: float
    whale_edge_penalty: float

    # Storage
    db_path: str

    # Alerts
    alert_telegram_bot_token: str
    alert_telegram_chat_id: str
    alert_discord_webhook: str
    alert_slack_webhook: str
    alert_cooldown_seconds: int

    # Logging
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            polymarket_gamma_url=_env_str("POLYMARKET_GAMMA_URL", "https://gamma-api.polymarket.com"),
            generator_model=_env_str("GENERATOR_MODEL", "gpt-4o-mini"),
            generator_api_key=_env_str("GENERATOR_API_KEY", ""),
            generator_base_url=_env_str("GENERATOR_BASE_URL", ""),
            generator_temperature=_env_float("GENERATOR_TEMPERATURE", 0.2),
            discriminator_model=_env_str("DISCRIMINATOR_MODEL", "glm-4.7"),
            discriminator_api_key=_env_str("DISCRIMINATOR_API_KEY", ""),
            discriminator_base_url=_env_str(
                "DISCRIMINATOR_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"
            ),
            discriminator_temperature=_env_float("DISCRIMINATOR_TEMPERATURE", 0.01),
            allow_mock_llm=_env_bool("ALLOW_MOCK_LLM", True),
            default_bankroll_usdc=_env_float("DEFAULT_BANKROLL_USDC", 10000.0),
            max_markets_per_cycle=_env_int("MAX_MARKETS_PER_CYCLE", 30),
            paper_ledger_path=_env_str("PAPER_LEDGER_PATH", "logs/paper_trades.jsonl"),
            decision_log_path=_env_str("DECISION_LOG_PATH", "logs/decisions.jsonl"),
            cycle_log_path=_env_str("CYCLE_LOG_PATH", "logs/cycles.jsonl"),
            graph_rag_pg_dsn=_env_str("GRAPH_RAG_PG_DSN", ""),
            graph_rag_top_k=_env_int("GRAPH_RAG_TOP_K", 8),
            serper_api_key=_env_str("SERPER_API_KEY", ""),
            serper_endpoint=_env_str("SERPER_ENDPOINT", "https://google.serper.dev/news"),
            serper_gl=_env_str("SERPER_GL", "us"),
            serper_hl=_env_str("SERPER_HL", "en"),
            serper_num=_env_int("SERPER_NUM", 8),
            min_liquidity_usdc=_env_float("MIN_LIQUIDITY_USDC", 3000.0),
            max_spread=_env_float("MAX_SPREAD", 0.05),
            min_hours_to_end=_env_float("MIN_HOURS_TO_END", 24.0),
            max_hours_to_end=_env_float("MAX_HOURS_TO_END", 24.0 * 14),
            min_net_edge=_env_float("MIN_NET_EDGE", 0.035),
            max_single_market_allocation=_env_float("MAX_SINGLE_MARKET_ALLOCATION", 0.025),
            min_trade_usdc=_env_float("MIN_TRADE_USDC", 10.0),
            kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
            # Kill switch
            kill_switch=_env_bool("KILL_SWITCH", False),
            # Drawdown heat system
            max_drawdown_pct=_env_float("MAX_DRAWDOWN_PCT", 0.20),
            warning_drawdown_pct=_env_float("WARNING_DRAWDOWN_PCT", 0.10),
            critical_drawdown_pct=_env_float("CRITICAL_DRAWDOWN_PCT", 0.15),
            auto_kill_at_max=_env_bool("AUTO_KILL_AT_MAX", True),
            # Daily loss limit
            max_daily_loss_usdc=_env_float("MAX_DAILY_LOSS_USDC", 500.0),
            # Position management
            stop_loss_pct=_env_float("STOP_LOSS_PCT", 0.20),
            take_profit_pct=_env_float("TAKE_PROFIT_PCT", 0.30),
            max_hold_hours=_env_float("MAX_HOLD_HOURS", 336.0),
            # Calibration
            calibration_extreme_threshold=_env_float("CALIBRATION_EXTREME_THRESHOLD", 0.15),
            calibration_evidence_penalty_weight=_env_float("CALIBRATION_EVIDENCE_PENALTY_WEIGHT", 0.30),
            calibration_contradiction_penalty_weight=_env_float("CALIBRATION_CONTRADICTION_PENALTY_WEIGHT", 0.20),
            calibration_auto_retrain_after=_env_int("CALIBRATION_AUTO_RETRAIN_AFTER", 30),
            # Cache
            gamma_cache_ttl_seconds=_env_int("GAMMA_CACHE_TTL_SECONDS", 300),
            serper_cache_ttl_seconds=_env_int("SERPER_CACHE_TTL_SECONDS", 3600),
            # Dashboard
            dashboard_host=_env_str("DASHBOARD_HOST", "127.0.0.1"),
            dashboard_port=_env_int("DASHBOARD_PORT", 2345),
            dashboard_api_key=_env_str("DASHBOARD_API_KEY", ""),
            cycle_interval_seconds=_env_int("CYCLE_INTERVAL_SECONDS", 900),
            recommended_cycle_interval_seconds=_env_int("RECOMMENDED_CYCLE_INTERVAL_SECONDS", 900),
            # Whale tracker
            whale_enabled=_env_bool("WHALE_ENABLED", False),
            whale_max_wallets=_env_int("WHALE_MAX_WALLETS", 20),
            whale_min_conviction=_env_float("WHALE_MIN_CONVICTION", 15.0),
            whale_edge_boost=_env_float("WHALE_EDGE_BOOST", 0.03),
            whale_edge_penalty=_env_float("WHALE_EDGE_PENALTY", 0.015),
            # Storage
            db_path=_env_str("DB_PATH", "data/polybot.db"),
            # Alerts
            alert_telegram_bot_token=_env_str("ALERT_TELEGRAM_BOT_TOKEN", ""),
            alert_telegram_chat_id=_env_str("ALERT_TELEGRAM_CHAT_ID", ""),
            alert_discord_webhook=_env_str("ALERT_DISCORD_WEBHOOK", ""),
            alert_slack_webhook=_env_str("ALERT_SLACK_WEBHOOK", ""),
            alert_cooldown_seconds=_env_int("ALERT_COOLDOWN_SECONDS", 300),
            # Logging
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )
