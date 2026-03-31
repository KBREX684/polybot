from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polybot.schemas import CalibrationRecord, EvidencePack, MarketCategory, MarketCandidate


def _platt_scale(prob: float, extreme_threshold: float = 0.15) -> float:
    """Compress extreme probabilities toward 0.5 using logistic scaling.

    If prob is in the extreme zone (< threshold or > 1-threshold),
    apply logistic compression pulling it toward 0.5.
    """
    if prob <= 0.0 or prob >= 1.0:
        return 0.5
    if extreme_threshold <= prob <= (1.0 - extreme_threshold):
        return prob
    # Logistic compression: shift toward 0.5
    center = 0.5
    distance = abs(prob - center)
    # Scale down the distance by a factor based on how extreme it is
    compression = 0.7  # reduce extreme distance by 30%
    new_distance = distance * compression
    return center + new_distance * (1.0 if prob > center else -1.0)


def _evidence_penalty(prob: float, evidence: EvidencePack, weight: float = 0.30) -> float:
    """Shift probability toward 0.5 when evidence quality is low."""
    if not evidence.items:
        # No evidence at all — strong shift toward 0.5
        return prob * (1.0 - weight) + 0.5 * weight

    avg_quality = sum(it.quality_score for it in evidence.items) / len(evidence.items)
    # Lower quality → stronger pull toward 0.5
    penalty = weight * (1.0 - avg_quality)
    return prob * (1.0 - penalty) + 0.5 * penalty


def _contradiction_penalty(prob: float, contradiction_score: float, weight: float = 0.20) -> float:
    """Shift probability toward 0.5 when evidence has high contradiction."""
    penalty = weight * contradiction_score
    return prob * (1.0 - penalty) + 0.5 * penalty


def _ensemble_spread_penalty(prob: float, discriminator_edge: float, spread_threshold: float = 0.10) -> float:
    """If discriminator significantly disagrees with generator, add uncertainty."""
    if abs(discriminator_edge) <= spread_threshold:
        return prob
    excess = min(abs(discriminator_edge) - spread_threshold, 0.20)
    penalty = 0.15 * excess / 0.20
    return prob * (1.0 - penalty) + 0.5 * penalty


def brier_score(forecast_prob: float, actual_outcome: float) -> float:
    """Calculate Brier score: (forecast - outcome)^2. Lower is better."""
    return (forecast_prob - actual_outcome) ** 2


class Calibrator:
    def __init__(
        self,
        log_path: str = "logs/calibration.jsonl",
        extreme_threshold: float = 0.15,
        evidence_penalty_weight: float = 0.30,
        contradiction_penalty_weight: float = 0.20,
        auto_retrain_after: int = 30,
    ) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.extreme_threshold = extreme_threshold
        self.evidence_penalty_weight = evidence_penalty_weight
        self.contradiction_penalty_weight = contradiction_penalty_weight
        self.auto_retrain_after = auto_retrain_after
        self._history: list[CalibrationRecord] = []
        self._load_history()

    def calibrate(
        self,
        raw_prob: float,
        evidence: EvidencePack,
        discriminator_edge: float = 0.0,
        category: MarketCategory = "OTHER",
        market_id: str = "",
    ) -> float:
        """Apply full calibration pipeline to a raw probability."""
        # Step 1: Platt scaling for extreme probabilities
        prob = _platt_scale(raw_prob, self.extreme_threshold)

        # Step 2: Evidence quality penalty
        prob = _evidence_penalty(prob, evidence, self.evidence_penalty_weight)

        # Step 3: Contradiction penalty
        prob = _contradiction_penalty(prob, evidence.contradiction_score, self.contradiction_penalty_weight)

        # Step 4: Ensemble spread penalty (discriminator disagreement)
        prob = _ensemble_spread_penalty(prob, discriminator_edge)

        prob = max(0.01, min(0.99, prob))

        # Log calibration record
        record = CalibrationRecord(
            timestamp=datetime.now(tz=timezone.utc),
            market_id=market_id,
            category=category,
            raw_prob=raw_prob,
            calibrated_prob=prob,
        )
        self._log_record(record)

        return round(prob, 6)

    def resolve(self, market_id: str, actual_outcome: float) -> float | None:
        """Update a calibration record with the actual outcome and compute Brier score."""
        for record in reversed(self._history):
            if record.market_id == market_id and record.actual_outcome is None:
                record.actual_outcome = actual_outcome
                record.brier_score = brier_score(record.calibrated_prob, actual_outcome)
                self._rewrite_history()
                return record.brier_score
        return None

    def average_brier(self) -> float:
        """Average Brier score across all resolved forecasts."""
        resolved = [r for r in self._history if r.brier_score is not None]
        if not resolved:
            return 0.0
        return sum(r.brier_score for r in resolved) / len(resolved)

    def category_brier(self, category: MarketCategory) -> float:
        """Average Brier score for a specific category."""
        resolved = [r for r in self._history if r.brier_score is not None and r.category == category]
        if not resolved:
            return 0.0
        return sum(r.brier_score for r in resolved) / len(resolved)

    def should_retrain(self) -> bool:
        resolved = [r for r in self._history if r.actual_outcome is not None]
        return len(resolved) >= self.auto_retrain_after

    def _log_record(self, record: CalibrationRecord) -> None:
        self._history.append(record)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _load_history(self) -> None:
        if not self.log_path.exists():
            return
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._history.append(CalibrationRecord.model_validate(data))
                except Exception:
                    continue

    def _rewrite_history(self) -> None:
        with self.log_path.open("w", encoding="utf-8") as f:
            for rec in self._history:
                f.write(json.dumps(rec.model_dump(mode="json"), ensure_ascii=False) + "\n")
