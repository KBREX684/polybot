from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from flask import Flask, jsonify, render_template

from src.polybot.config import Settings


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.exists():
        return []
    rows: list[dict[str, Any]] = []
    with file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _count_recent(rows: list[dict[str, Any]], ts_key: str, within: timedelta) -> int:
    now = datetime.now(tz=timezone.utc)
    threshold = now - within
    count = 0
    for r in rows:
        dt = _parse_ts(r.get(ts_key))
        if dt and dt >= threshold:
            count += 1
    return count


def _aggregate(decisions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(decisions)
    filter_passed = sum(1 for d in decisions if d.get("filter_passed"))
    risk_passed = sum(1 for d in decisions if d.get("risk_decision", {}).get("passed"))
    verdicts = [d.get("discriminator_output", {}).get("verdict", "unknown") for d in decisions]
    accepts = sum(1 for v in verdicts if v == "accept")
    rejects = sum(1 for v in verdicts if v == "reject")
    revisions = sum(1 for v in verdicts if v == "revise")
    edges = [float(d.get("discriminator_output", {}).get("final_edge", 0.0)) for d in decisions]
    confs = [float(d.get("discriminator_output", {}).get("final_confidence", 0.0)) for d in decisions]

    executed = len(trades)
    traded_usdc = sum(float(t.get("size_usdc", 0.0)) for t in trades)

    return {
        "decisions_total": total,
        "filter_passed": filter_passed,
        "risk_passed": risk_passed,
        "accepts": accepts,
        "rejects": rejects,
        "revisions": revisions,
        "executed": executed,
        "traded_usdc": round(traded_usdc, 2),
        "avg_edge": round(mean(edges), 4) if edges else 0.0,
        "avg_confidence": round(mean(confs), 4) if confs else 0.0,
    }


def _pipeline_counts(decisions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, int]:
    scanned = len(decisions)
    hard_filter = sum(1 for d in decisions if d.get("filter_passed"))
    generated = sum(1 for d in decisions if d.get("generator_output", {}).get("side") != "NO_TRADE")
    reviewed = sum(
        1
        for d in decisions
        if d.get("discriminator_output", {}).get("verdict") in {"accept", "reject", "revise"}
    )
    risk = sum(1 for d in decisions if d.get("risk_decision", {}).get("passed"))
    executed = len(trades)
    return {
        "scanned": scanned,
        "hard_filter": hard_filter,
        "generated": generated,
        "reviewed": reviewed,
        "risk": risk,
        "executed": executed,
    }


def _runtime_stats(
    decisions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    decisions_1h = _count_recent(decisions, "timestamp", timedelta(hours=1))
    trades_1h = _count_recent(trades, "timestamp", timedelta(hours=1))
    cycles_1h = _count_recent(cycles, "timestamp", timedelta(hours=1))
    interval = max(1, settings.cycle_interval_seconds)
    est_cycles_per_hour = round(3600 / interval, 2)
    # Approx API budget per hour heuristic:
    # - 1 gamma market pull / cycle
    # - ~3 serper queries / passed market (worst case approximated by limit ratio)
    # - 2 LLM calls / passed market
    est_api_calls_per_hour = round(est_cycles_per_hour * (1 + settings.max_markets_per_cycle * 2))
    return {
        "cycle_interval_seconds": interval,
        "recommended_cycle_interval_seconds": settings.recommended_cycle_interval_seconds,
        "decisions_last_hour": decisions_1h,
        "trades_last_hour": trades_1h,
        "cycles_last_hour": cycles_1h,
        "estimated_cycles_per_hour": est_cycles_per_hour,
        "estimated_api_calls_per_hour": est_api_calls_per_hour,
    }


def create_app(settings: Settings | None = None) -> Flask:
    s = settings or Settings.from_env()
    template_folder = str(Path(__file__).parent / "templates")
    static_folder = str(Path(__file__).parent / "static")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

    @app.get("/")
    def dashboard() -> str:
        decisions = _read_jsonl(s.decision_log_path)
        trades = _read_jsonl(s.paper_ledger_path)
        cycles = _read_jsonl(s.cycle_log_path)
        stats = _aggregate(decisions, trades)
        flow = _pipeline_counts(decisions, trades)
        runtime = _runtime_stats(decisions, trades, cycles, s)
        recent_decisions = list(reversed(decisions[-12:]))
        recent_trades = list(reversed(trades[-12:]))
        return render_template(
            "dashboard.html",
            stats=stats,
            flow=flow,
            runtime=runtime,
            recent_decisions=recent_decisions,
            recent_trades=recent_trades,
        )

    @app.get("/api/metrics")
    def metrics() -> Any:
        decisions = _read_jsonl(s.decision_log_path)
        trades = _read_jsonl(s.paper_ledger_path)
        cycles = _read_jsonl(s.cycle_log_path)
        payload = {
            "stats": _aggregate(decisions, trades),
            "flow": _pipeline_counts(decisions, trades),
            "runtime": _runtime_stats(decisions, trades, cycles, s),
            "recent_decisions": list(reversed(decisions[-20:])),
            "recent_trades": list(reversed(trades[-20:])),
        }
        return jsonify(payload)

    return app
