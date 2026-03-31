from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import requests
from flask import Flask, Response, jsonify, render_template, request

from src.polybot.config import Settings
from src.polybot.storage.database import Database


def _fetch_live_price(gamma_url: str, market_id: str) -> float | None:
    """Fetch current YES price from Gamma API for a single market."""
    try:
        resp = requests.get(
            f"{gamma_url}/markets/{market_id}",
            timeout=10,
            headers={"User-Agent": "polybot-v2"},
        )
        resp.raise_for_status()
        raw = resp.json()
        prices = raw.get("outcomePrices", [])
        if isinstance(prices, str):
            prices = json.loads(prices)
        if prices:
            return float(prices[0])
    except Exception:
        pass
    return None


def _calc_pnl(side: str, entry_price: float, current_price: float, size_usdc: float) -> float:
    if entry_price <= 0:
        return 0.0
    if side == "BUY_YES":
        return (current_price - entry_price) / entry_price * size_usdc
    return (entry_price - current_price) / entry_price * size_usdc


def create_app(settings: Settings | None = None, db: Database | None = None) -> Flask:
    s = settings or Settings.from_env()
    database = db or Database(db_path=s.db_path)

    template_folder = str(Path(__file__).parent / "templates")
    static_folder = str(Path(__file__).parent / "static")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

    # Optional API key auth
    def _check_auth() -> Response | None:
        if not s.dashboard_api_key:
            return None
        key = request.headers.get("X-API-Key", "") or request.args.get("api_key", "")
        if key != s.dashboard_api_key:
            return jsonify({"error": "unauthorized"}), 401
        return None

    @app.get("/")
    def dashboard() -> str:
        stats = database.stats_summary()
        open_positions = database.query_open_positions()
        recent_decisions = database.query_decisions(limit=15)
        recent_trades = database.query_trades(limit=15)
        equity_curve = database.equity_curve(limit=200)
        integrity = database.verify_integrity()
        whale_smi = None
        if s.whale_enabled:
            try:
                whale_rows = database._conn.execute(
                    "SELECT AVG(conviction) as avg_conv FROM whale_scores WHERE scanned_at > datetime('now', '-1 hour')"
                ).fetchone()
                whale_smi = round(whale_rows["avg_conv"], 1) if whale_rows and whale_rows["avg_conv"] else 0.0
            except Exception:
                whale_smi = 0.0

        return render_template(
            "dashboard.html",
            stats=stats,
            open_positions=open_positions,
            recent_decisions=recent_decisions,
            recent_trades=recent_trades,
            equity_curve=equity_curve,
            integrity=integrity,
            whale_smi=whale_smi,
            settings_vars={
                "kill_switch": s.kill_switch,
                "whale_enabled": s.whale_enabled,
                "paper_mode": True,
                "generator_model": s.generator_model,
                "discriminator_model": s.discriminator_model,
                "bankroll": s.default_bankroll_usdc,
                "cycle_interval": s.cycle_interval_seconds,
            },
        )

    @app.get("/api/metrics")
    def metrics() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        stats = database.stats_summary()
        open_positions = database.query_open_positions()
        recent_decisions = database.query_decisions(limit=20)
        recent_trades = database.query_trades(limit=20)
        equity_curve = database.equity_curve(limit=200)
        integrity = database.verify_integrity()
        payload = {
            "stats": stats,
            "open_positions": open_positions,
            "recent_decisions": recent_decisions,
            "recent_trades": recent_trades,
            "equity_curve": equity_curve,
            "integrity": integrity,
        }
        return jsonify(payload)

    @app.get("/api/equity-curve")
    def equity_curve_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        limit = request.args.get("limit", 200, type=int)
        return jsonify(database.equity_curve(limit=limit))

    @app.get("/api/positions")
    def positions_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        return jsonify(database.query_open_positions())

    @app.get("/api/positions-pnl")
    def positions_pnl_api() -> tuple[Any, int] | Any:
        """Open positions enriched with live PnL from Gamma API."""
        auth = _check_auth()
        if auth:
            return auth
        positions = database.query_open_positions()
        enriched = []
        for p in positions:
            live_price = _fetch_live_price(s.polymarket_gamma_url, p["market_id"])
            if live_price is not None:
                pnl = _calc_pnl(p["side"], p["entry_price"], live_price, p["size_usdc"])
                p["live_price"] = round(live_price, 4)
                p["live_pnl"] = round(pnl, 2)
                p["live_pnl_pct"] = round(pnl / p["size_usdc"] * 100, 2) if p["size_usdc"] > 0 else 0.0
            else:
                p["live_price"] = p["current_price"]
                p["live_pnl"] = 0.0
                p["live_pnl_pct"] = 0.0
            enriched.append(p)
        return jsonify(enriched)

    @app.get("/api/decisions")
    def decisions_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        return jsonify(database.query_decisions(limit=limit, offset=offset))

    @app.get("/api/trades")
    def trades_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        limit = request.args.get("limit", 50, type=int)
        return jsonify(database.query_trades(limit=limit))

    @app.get("/api/integrity")
    def integrity_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        return jsonify(database.verify_integrity())

    @app.get("/api/whale")
    def whale_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        try:
            rows = database._conn.execute(
                "SELECT * FROM whale_scores ORDER BY scanned_at DESC LIMIT 50"
            ).fetchall()
            return jsonify([dict(r) for r in rows])
        except Exception:
            return jsonify([])

    @app.post("/api/kill-switch")
    def kill_switch_api() -> tuple[Any, int] | Any:
        auth = _check_auth()
        if auth:
            return auth
        body = request.get_json(silent=True) or {}
        new_state = body.get("enabled", True)
        import os
        os.environ["KILL_SWITCH"] = str(new_state).lower()
        return jsonify({"kill_switch": new_state, "message": f"Kill switch {'activated' if new_state else 'deactivated'}"})

    @app.get("/health")
    def health() -> tuple[Any, int] | Any:
        return jsonify({"status": "ok", "timestamp": datetime.now(tz=timezone.utc).isoformat()})

    return app
