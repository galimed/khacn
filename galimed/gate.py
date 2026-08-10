"""GALIMED commercial gate — free-tier limiting and licensing enforcement.

WHY THIS EXISTS, AND WHY IT IS SEPARATE FROM news2.py
-------------------------------------------------------
news2.py is the clinical core: pure, deterministic, and must stay testable
and usable without any commercial restriction — a clinician or a researcher
auditing the score must be able to import it and call score_vitals() with
nothing standing between them and the algorithm.

This module is the opposite: it has nothing to do with clinical correctness
and everything to do with the business model. It wraps *any* scoring
function (score_vitals from news2.py, score_qsofa from qsofa.py, ...) with:

  - no license: capped at FREE_TIER_LIMIT successful scorings, each result
    watermarked and pointed at https://galimedai.org for licensing;
  - a valid license (see licensing.py): unlimited, no watermark.

Keeping this in its own file means the clinical modules have zero knowledge
that a commercial layer exists. See LICENSE for the legal terms this
technical gate backs, and COMMERCIAL.md for how a license is obtained.

No third-party dependencies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import licensing

__all__ = [
    "Gate",
    "GatedResult",
    "UsageLimitExceededError",
    "GALIMEDAI_URL",
]

GALIMEDAI_URL = "https://galimedai.org"


class UsageLimitExceededError(RuntimeError):
    """Raised when an unlicensed caller has used up the free tier."""


@dataclass(frozen=True)
class GatedResult:
    """A scoring result wrapped with commercial-gate metadata.

    `value` is exactly what the wrapped scoring function returned — this
    module never inspects or modifies it. `watermark` is None when
    `licensed` is True; otherwise it is a banner meant to be shown alongside
    `value`, never silently discarded.
    """

    value: object
    licensed: bool
    remaining_free_scorings: Optional[int]
    watermark: Optional[str]


def _default_usage_path() -> Path:
    return Path.home() / ".galimed" / "usage.json"


def _watermark_text(remaining: int) -> str:
    return (
        f"[GALIMED — évaluation non licenciée. {remaining} scoring(s) gratuit(s) "
        f"restant(s) sur {Gate.FREE_TIER_LIMIT}. Usage clinique ou commercial interdit "
        f"sans licence. Informations et licences : {GALIMEDAI_URL}]"
    )


class Gate:
    """Wraps scoring calls with the free-tier cap / license check.

    A local JSON file tracks how many free scorings have been used. This is
    a soft counter, not a tamper-resistant one — deleting the file resets
    it. That is a deliberate scope choice: the thing that makes bypassing it
    a problem is LICENSE's anti-circumvention clause, not an arms race in
    this file. gate.py's job is to make honest use easy and unlicensed
    overuse visible (via the watermark), not to defeat a determined attacker.
    """

    FREE_TIER_LIMIT = 25

    def __init__(
        self,
        license_key: Optional[str] = None,
        usage_path: Optional[Path] = None,
        public_key: bytes = licensing.GALIMED_PUBLIC_KEY,
        today: Optional[date] = None,
    ):
        self._license = (
            licensing.verify_license(license_key, public_key=public_key, today=today)
            if license_key
            else None
        )
        self._usage_path = Path(usage_path) if usage_path else _default_usage_path()

    @property
    def licensed(self) -> bool:
        return self._license is not None

    @property
    def license(self) -> Optional[licensing.License]:
        return self._license

    @property
    def remaining_free_scorings(self) -> Optional[int]:
        """None when licensed (no cap). Otherwise the count left, floored at 0."""
        if self.licensed:
            return None
        return max(0, self.FREE_TIER_LIMIT - self._read_count())

    def score(self, scoring_fn: Callable, *args, **kwargs) -> GatedResult:
        """Call `scoring_fn(*args, **kwargs)` through the gate.

        Licensed: runs unlimited, no watermark. Unlicensed: raises
        UsageLimitExceededError if the free tier is already spent, otherwise
        runs the scoring, counts it, and returns a watermarked result. A
        scoring_fn that raises (e.g. invalid vitals) never consumes a free
        scoring — only a completed scoring counts.
        """
        if self.licensed:
            value = scoring_fn(*args, **kwargs)
            return GatedResult(value=value, licensed=True, remaining_free_scorings=None, watermark=None)

        if self._read_count() >= self.FREE_TIER_LIMIT:
            raise UsageLimitExceededError(
                f"Limite de {self.FREE_TIER_LIMIT} scorings gratuits atteinte. "
                f"Une licence est requise pour continuer : {GALIMEDAI_URL}"
            )

        value = scoring_fn(*args, **kwargs)

        new_count = self._increment_count()
        remaining = max(0, self.FREE_TIER_LIMIT - new_count)
        return GatedResult(
            value=value,
            licensed=False,
            remaining_free_scorings=remaining,
            watermark=_watermark_text(remaining),
        )

    def _read_count(self) -> int:
        try:
            data = json.loads(self._usage_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return 0
        count = data.get("count", 0) if isinstance(data, dict) else 0
        return count if isinstance(count, int) and count >= 0 else 0

    def _increment_count(self) -> int:
        count = self._read_count() + 1
        self._usage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._usage_path.with_name(self._usage_path.name + ".tmp")
        tmp_path.write_text(json.dumps({"count": count}), encoding="utf-8")
        tmp_path.replace(self._usage_path)
        return count


if __name__ == "__main__":  # pragma: no cover - manual demo
    import tempfile

    import news2

    demo_vitals = news2.Vitals(
        respiratory_rate=16, spo2=98, on_oxygen=False, systolic_bp=120,
        pulse=70, consciousness=news2.Consciousness.ALERT, temperature=36.8,
    )
    with tempfile.TemporaryDirectory() as tmp:
        gate = Gate(usage_path=Path(tmp) / "usage.json")
        result = gate.score(news2.score_vitals, demo_vitals)
        print("licensed:", result.licensed)
        print("remaining free scorings:", result.remaining_free_scorings)
        print(result.watermark)
        print("NEWS2 total:", result.value.total)
