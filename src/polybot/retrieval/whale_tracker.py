from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polybot.schemas import MarketCandidate


class WhaleWallet:
    __slots__ = ("address", "pnl_usdc", "win_rate", "rank", "last_active")

    def __init__(self, address: str, pnl_usdc: float = 0.0, win_rate: float = 0.0, rank: int = 0, last_active: str = "") -> None:
        self.address = address
        self.pnl_usdc = pnl_usdc
        self.win_rate = win_rate
        self.rank = rank
        self.last_active = last_active

    def to_dict(self) -> dict[str, Any]:
        return {"address": self.address, "pnl_usdc": self.pnl_usdc, "win_rate": self.win_rate, "rank": self.rank}


class WhaleSignal:
    __slots__ = ("market_id", "whale_count_yes", "whale_count_no", "total_whales", "conviction", "edge_boost")

    def __init__(
        self,
        market_id: str,
        whale_count_yes: int = 0,
        whale_count_no: int = 0,
        total_whales: int = 0,
        conviction: float = 0.0,
        edge_boost: float = 0.0,
    ) -> None:
        self.market_id = market_id
        self.whale_count_yes = whale_count_yes
        self.whale_count_no = whale_count_no
        self.total_whales = total_whales
        self.conviction = conviction
        self.edge_boost = edge_boost

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "whale_count_yes": self.whale_count_yes,
            "whale_count_no": self.whale_count_no,
            "total_whales": self.total_whales,
            "conviction": round(self.conviction, 4),
            "edge_boost": round(self.edge_boost, 6),
        }


class WhaleTracker:
    """MVP Whale Tracker — scrapes Polymarket leaderboard + positions via Gamma API.

    Uses public Gamma API endpoints to discover top wallets and their positions.
    No private API keys required.
    """

    LEADERBOARD_URL = "https://gamma-api.polymarket.com/leaderboard"
    POSITIONS_URL = "https://data-api.polymarket.com/positions"

    def __init__(
        self,
        max_wallets: int = 20,
        min_conviction_score: float = 15.0,
        conviction_edge_boost: float = 0.03,
        conviction_edge_penalty: float = 0.015,
        cache_path: str = "logs/whale_cache.json",
    ) -> None:
        self.max_wallets = max_wallets
        self.min_conviction_score = min_conviction_score
        self.conviction_edge_boost = conviction_edge_boost
        self.conviction_edge_penalty = conviction_edge_penalty
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._wallets: list[WhaleWallet] = []
        self._wallet_positions: dict[str, dict[str, str]] = {}  # wallet -> {market_id: side}
        self._signals: dict[str, WhaleSignal] = {}

    @property
    def wallets(self) -> list[WhaleWallet]:
        return self._wallets

    @property
    def signals(self) -> dict[str, WhaleSignal]:
        return self._signals

    def fetch_leaderboard(self) -> list[WhaleWallet]:
        """Fetch top wallets from Polymarket leaderboard API."""
        import requests

        try:
            resp = requests.get(
                self.LEADERBOARD_URL,
                params={"limit": self.max_wallets},
                timeout=15,
                headers={"User-Agent": "polybot-whale/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                # Some API versions wrap in a key
                data = data.get("leaderboard", data.get("data", []))
                if not isinstance(data, list):
                    data = []
        except Exception:
            data = []

        wallets: list[WhaleWallet] = []
        for i, entry in enumerate(data[:self.max_wallets]):
            addr = str(entry.get("address", entry.get("wallet", entry.get("id", "")))).strip()
            if not addr:
                continue
            w = WhaleWallet(
                address=addr,
                pnl_usdc=float(entry.get("pnl", entry.get("profit", 0.0)) or 0.0),
                win_rate=float(entry.get("winRate", entry.get("win_rate", 0.0)) or 0.0),
                rank=i + 1,
                last_active=str(entry.get("lastActive", "")),
            )
            wallets.append(w)

        self._wallets = wallets
        return wallets

    def fetch_wallet_positions(self, wallet_address: str) -> dict[str, str]:
        """Fetch current positions for a single wallet. Returns {market_id: side}."""
        import requests

        try:
            resp = requests.get(
                self.POSITIONS_URL,
                params={"user": wallet_address, "sizeThreshold": "50"},
                timeout=10,
                headers={"User-Agent": "polybot-whale/1.0"},
            )
            resp.raise_for_status()
            positions = resp.json()
            if not isinstance(positions, list):
                return {}
        except Exception:
            return {}

        result: dict[str, str] = {}
        for pos in positions:
            mid = str(pos.get("market", pos.get("marketSlug", pos.get("conditionId", ""))))
            size = float(pos.get("size", pos.get("outcomeTokensBought", 0)) or 0)
            if size <= 0:
                continue
            outcome = str(pos.get("outcome", pos.get("side", ""))).upper()
            if "YES" in outcome:
                result[mid] = "YES"
            elif "NO" in outcome:
                result[mid] = "NO"
        return result

    def scan_markets(self, candidate_market_ids: list[str]) -> dict[str, WhaleSignal]:
        """Build whale conviction signals for each candidate market.

        For each market, count how many whales are YES vs NO, compute conviction,
        and derive an edge boost/penalty.
        """
        if not self._wallets:
            self.fetch_leaderboard()

        # Collect positions from all tracked wallets
        all_positions: dict[str, dict[str, str]] = {}
        for w in self._wallets:
            positions = self.fetch_wallet_positions(w.address)
            all_positions[w.address] = positions
            self._wallet_positions[w.address] = positions

        # Build signals per market
        signals: dict[str, WhaleSignal] = {}
        for mid in candidate_market_ids:
            yes_count = 0
            no_count = 0
            for wallet_positions in all_positions.values():
                side = wallet_positions.get(mid)
                if side == "YES":
                    yes_count += 1
                elif side == "NO":
                    no_count += 1

            total = yes_count + no_count
            if total == 0:
                signals[mid] = WhaleSignal(market_id=mid)
                continue

            # Conviction: whale_count × agreement_ratio
            majority = max(yes_count, no_count)
            conviction = total * (majority / total) * 10.0

            # Edge boost/penalty
            if conviction >= self.min_conviction_score:
                edge_boost = self.conviction_edge_boost * (conviction / 50.0)
            else:
                edge_boost = 0.0

            signals[mid] = WhaleSignal(
                market_id=mid,
                whale_count_yes=yes_count,
                whale_count_no=no_count,
                total_whales=total,
                conviction=round(conviction, 2),
                edge_boost=round(min(edge_boost, self.conviction_edge_boost), 6),
            )

        self._signals = signals
        self._save_cache()
        return signals

    def get_signal(self, market_id: str) -> WhaleSignal | None:
        return self._signals.get(market_id)

    def smart_money_index(self) -> float:
        """Aggregate SMI: 0-100 bullish/bearish reading across all tracked markets."""
        if not self._signals:
            return 50.0
        yes_total = sum(s.whale_count_yes for s in self._signals.values())
        no_total = sum(s.whale_count_no for s in self._signals.values())
        total = yes_total + no_total
        if total == 0:
            return 50.0
        return round(yes_total / total * 100, 1)

    def _save_cache(self) -> None:
        data = {
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "wallets": [w.to_dict() for w in self._wallets],
            "signals": {mid: s.to_dict() for mid, s in self._signals.items()},
        }
        with self.cache_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_cache(self) -> bool:
        if not self.cache_path.exists():
            return False
        try:
            with self.cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self._wallets = [WhaleWallet(**w) for w in data.get("wallets", [])]
            for mid, sd in data.get("signals", {}).items():
                self._signals[mid] = WhaleSignal(**sd)
            return True
        except Exception:
            return False
