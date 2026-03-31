from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polybot.observability.logger import get_logger

log = get_logger("storage")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    market_id TEXT NOT NULL,
    question TEXT,
    category TEXT,
    filter_passed INTEGER NOT NULL DEFAULT 0,
    filter_reasons TEXT DEFAULT '[]',
    generator_output TEXT DEFAULT '{}',
    discriminator_output TEXT DEFAULT '{}',
    risk_decision TEXT DEFAULT '{}',
    executed_trade TEXT,
    calibrated_prob REAL,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'paper',
    status TEXT NOT NULL DEFAULT 'filled',
    market_id TEXT NOT NULL,
    side TEXT NOT NULL,
    size_usdc REAL NOT NULL,
    fill_price REAL NOT NULL,
    reason_code TEXT,
    checksum TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL UNIQUE,
    question TEXT,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    size_usdc REAL NOT NULL,
    opened_at TEXT NOT NULL,
    stop_loss_price REAL DEFAULT 0,
    take_profit_price REAL DEFAULT 1,
    max_hold_hours REAL DEFAULT 336,
    category TEXT DEFAULT 'OTHER',
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    close_reason TEXT,
    close_pnl REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS calibration (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    market_id TEXT NOT NULL,
    category TEXT NOT NULL,
    raw_prob REAL NOT NULL,
    calibrated_prob REAL NOT NULL,
    actual_outcome REAL,
    brier_score REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS whale_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id TEXT NOT NULL,
    whale_count_yes INTEGER DEFAULT 0,
    whale_count_no INTEGER DEFAULT 0,
    total_whales INTEGER DEFAULT 0,
    conviction REAL DEFAULT 0,
    edge_boost REAL DEFAULT 0,
    scanned_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_decisions_market_id ON decisions (market_id);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions (timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_market_id ON trades (market_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades (timestamp);
CREATE INDEX IF NOT EXISTS idx_positions_market_id ON positions (market_id);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status);
CREATE INDEX IF NOT EXISTS idx_calibration_market_id ON calibration (market_id);
CREATE INDEX IF NOT EXISTS idx_cycles_timestamp ON cycles (timestamp);
"""


def _checksum(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


class Database:
    """SQLite WAL storage with SHA-256 audit integrity."""

    def __init__(self, db_path: str = "data/polybot.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Decisions ---
    def insert_decision(
        self,
        market_id: str,
        question: str = "",
        filter_passed: bool = False,
        filter_reasons: list[str] | None = None,
        generator_output: dict | None = None,
        discriminator_output: dict | None = None,
        risk_decision: dict | None = None,
        executed_trade: dict | None = None,
        category: str | None = None,
        calibrated_prob: float | None = None,
    ) -> int:
        ts = datetime.now(tz=timezone.utc).isoformat()
        payload = json.dumps({
            "market_id": market_id, "question": question,
            "filter_passed": filter_passed, "timestamp": ts,
        }, ensure_ascii=False)
        checksum = _checksum(payload)
        cur = self._conn.execute(
            """INSERT INTO decisions
               (timestamp, market_id, question, category, filter_passed, filter_reasons,
                generator_output, discriminator_output, risk_decision, executed_trade,
                calibrated_prob, checksum)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts, market_id, question, category, int(filter_passed),
                json.dumps(filter_reasons or [], ensure_ascii=False),
                json.dumps(generator_output or {}, ensure_ascii=False),
                json.dumps(discriminator_output or {}, ensure_ascii=False),
                json.dumps(risk_decision or {}, ensure_ascii=False),
                json.dumps(executed_trade, ensure_ascii=False) if executed_trade else None,
                calibrated_prob, checksum,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query_decisions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM decisions ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_decisions(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()
        return row[0] if row else 0

    # --- Trades ---
    def insert_trade(self, market_id: str, side: str, size_usdc: float, fill_price: float,
                     reason_code: str = "", mode: str = "paper") -> int:
        ts = datetime.now(tz=timezone.utc).isoformat()
        payload = json.dumps({"market_id": market_id, "side": side, "ts": ts}, ensure_ascii=False)
        checksum = _checksum(payload)
        cur = self._conn.execute(
            """INSERT INTO trades (timestamp, mode, status, market_id, side, size_usdc,
               fill_price, reason_code, checksum) VALUES (?, ?, 'filled', ?, ?, ?, ?, ?, ?)""",
            (ts, mode, market_id, side, size_usdc, fill_price, reason_code, checksum),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query_trades(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_trades(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return row[0] if row else 0

    # --- Positions ---
    def open_position(self, market_id: str, question: str = "", side: str = "BUY_YES",
                      entry_price: float = 0.5, size_usdc: float = 0.0,
                      opened_at: str = "", stop_loss: float = 0.0,
                      take_profit: float = 1.0, max_hold_hours: float = 336.0,
                      category: str = "OTHER") -> int:
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO positions
               (market_id, question, side, entry_price, current_price, size_usdc,
                opened_at, stop_loss_price, take_profit_price, max_hold_hours, category, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (market_id, question, side, entry_price, entry_price, size_usdc,
             opened_at, stop_loss, take_profit, max_hold_hours, category),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def close_position(self, market_id: str, close_reason: str, close_pnl: float,
                       current_price: float) -> bool:
        self._conn.execute(
            """UPDATE positions SET status='closed', closed_at=?, close_reason=?, close_pnl=?,
               current_price=? WHERE market_id=? AND status='open'""",
            (datetime.now(tz=timezone.utc).isoformat(), close_reason, close_pnl, current_price, market_id),
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def query_open_positions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE status='open' ORDER BY opened_at DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_open_positions(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()
        return row[0] if row else 0

    # --- Cycles ---
    def insert_cycle(self, summary: dict[str, Any]) -> int:
        ts = datetime.now(tz=timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO cycles (timestamp, summary_json) VALUES (?, ?)",
            (ts, json.dumps(summary, ensure_ascii=False)),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def query_cycles(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Calibration ---
    def insert_calibration(self, market_id: str, category: str, raw_prob: float,
                           calibrated_prob: float) -> int:
        ts = datetime.now(tz=timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO calibration (timestamp, market_id, category, raw_prob, calibrated_prob)
               VALUES (?, ?, ?, ?, ?)""",
            (ts, market_id, category, raw_prob, calibrated_prob),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def resolve_calibration(self, market_id: str, actual_outcome: float) -> float | None:
        """Update calibration record with outcome and compute Brier score."""
        row = self._conn.execute(
            "SELECT id, calibrated_prob FROM calibration WHERE market_id=? AND actual_outcome IS NULL ORDER BY id DESC LIMIT 1",
            (market_id,),
        ).fetchone()
        if not row:
            return None
        brier = (row["calibrated_prob"] - actual_outcome) ** 2
        self._conn.execute(
            "UPDATE calibration SET actual_outcome=?, brier_score=? WHERE id=?",
            (actual_outcome, brier, row["id"]),
        )
        self._conn.commit()
        return brier

    def average_brier(self) -> float:
        row = self._conn.execute(
            "SELECT AVG(brier_score) as avg_b FROM calibration WHERE brier_score IS NOT NULL"
        ).fetchone()
        return row["avg_b"] if row and row["avg_b"] is not None else 0.0

    # --- Whale Scores ---
    def upsert_whale_score(self, market_id: str, yes: int = 0, no: int = 0, total: int = 0,
                           conviction: float = 0.0, edge_boost: float = 0.0) -> int:
        ts = datetime.now(tz=timezone.utc).isoformat()
        cur = self._conn.execute(
            """INSERT INTO whale_scores (market_id, whale_count_yes, whale_count_no,
               total_whales, conviction, edge_boost, scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (market_id, yes, no, total, conviction, edge_boost, ts),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # --- Analytics ---
    def equity_curve(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get bankroll snapshots from cycle summaries."""
        rows = self._conn.execute(
            "SELECT timestamp, summary_json FROM cycles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        curve: list[dict[str, Any]] = []
        for r in reversed(rows):
            try:
                data = json.loads(r["summary_json"])
                curve.append({
                    "timestamp": r["timestamp"],
                    "bankroll": data.get("bankroll_after_cycle", 0),
                    "drawdown_level": data.get("drawdown_level_final", "normal"),
                    "open_positions": data.get("open_positions", 0),
                })
            except Exception:
                continue
        return curve

    def stats_summary(self) -> dict[str, Any]:
        total_decisions = self.count_decisions()
        total_trades = self.count_trades()
        filter_passed = self._conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE filter_passed=1"
        ).fetchone()[0]
        risk_passed = self._conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE json_extract(risk_decision, '$.passed')=1"
        ).fetchone()[0]
        traded_usdc = self._conn.execute(
            "SELECT COALESCE(SUM(size_usdc), 0) FROM trades"
        ).fetchone()[0]

        edges = self._conn.execute(
            """SELECT json_extract(discriminator_output, '$.final_edge') as e
               FROM decisions WHERE e IS NOT NULL"""
        ).fetchall()
        edge_vals = [abs(r["e"]) for r in edges if r["e"] is not None]

        confs = self._conn.execute(
            """SELECT json_extract(discriminator_output, '$.final_confidence') as c
               FROM decisions WHERE c IS NOT NULL"""
        ).fetchall()
        conf_vals = [r["c"] for r in confs if r["c"] is not None]

        avg_edge = sum(edge_vals) / len(edge_vals) if edge_vals else 0.0
        avg_conf = sum(conf_vals) / len(conf_vals) if conf_vals else 0.0

        return {
            "decisions_total": total_decisions,
            "filter_passed": filter_passed,
            "risk_passed": risk_passed,
            "executed": total_trades,
            "traded_usdc": round(traded_usdc, 2),
            "avg_edge": round(avg_edge, 4),
            "avg_confidence": round(avg_conf, 4),
            "avg_brier_score": round(self.average_brier(), 4),
        }

    def verify_integrity(self) -> dict[str, Any]:
        """Verify SHA-256 checksums for all records."""
        total = 0
        valid = 0
        rows = self._conn.execute(
            "SELECT id, checksum, market_id, question, filter_passed, timestamp FROM decisions"
        ).fetchall()
        for r in rows:
            total += 1
            payload = json.dumps({
                "market_id": r["market_id"], "question": r["question"],
                "filter_passed": bool(r["filter_passed"]), "timestamp": r["timestamp"],
            }, ensure_ascii=False)
            if _checksum(payload) == r["checksum"]:
                valid += 1
        status = "OK" if total == valid else f"TAMPERED({total - valid})"
        return {"total": total, "valid": valid, "tampered": total - valid, "status": status}

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for key in ("filter_reasons", "generator_output", "discriminator_output",
                     "risk_decision", "executed_trade", "summary_json"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
