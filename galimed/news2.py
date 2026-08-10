"""NEWS2 — National Early Warning Score 2.

Implementation of the Royal College of Physicians (2017) NEWS2 standard for
early detection of clinical deterioration, for the GALIMED AI platform.

WHY THIS EXISTS
---------------
An AI pre-diagnosis platform must never let a generative model decide, on its
own, whether a patient is deteriorating. NEWS2 is a deterministic, published,
internationally validated scale. Computing it in plain code gives GALIMED a
reproducible clinical floor: the same vital signs always produce the same
score, auditable line by line, independent of any model.

Use it as a guardrail *around* the AI, not as something the AI produces.

CLINICAL SAFETY
---------------
NEWS2 is a triage / escalation aid. It is NOT a diagnosis, and it does not
replace clinical judgement. It is not validated for pregnancy, for children
under 16, or for spinal-cord-injury patients. A low score never overrides a
clinician's concern about a patient.

Reference: Royal College of Physicians. National Early Warning Score (NEWS) 2.
London: RCP, 2017.

No third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = [
    "Consciousness",
    "SpO2Scale",
    "RiskLevel",
    "Vitals",
    "ParameterScore",
    "News2Result",
    "score_vitals",
    "VitalsError",
]


class VitalsError(ValueError):
    """Raised when an observation is missing or physiologically implausible."""


class Consciousness(Enum):
    """ACVPU scale. Anything other than ALERT scores 3."""

    ALERT = "A"
    CONFUSION = "C"
    VOICE = "V"
    PAIN = "P"
    UNRESPONSIVE = "U"


class SpO2Scale(Enum):
    """Which oxygen-saturation scale applies to this patient.

    SCALE_1 is the default. SCALE_2 is used only when a clinician has
    prescribed a target range of 88-92% (typically hypercapnic respiratory
    failure, e.g. some COPD patients). Choosing the wrong scale materially
    changes the score, so it must be an explicit decision — never a default
    guessed by software.
    """

    SCALE_1 = 1
    SCALE_2 = 2


class RiskLevel(Enum):
    LOW = "low"
    LOW_MEDIUM = "low-medium"
    MEDIUM = "medium"
    HIGH = "high"


# Physiologically plausible input ranges. Values outside these are treated as
# data-entry errors and rejected loudly rather than silently scored — a typo
# that reads as a normal value is more dangerous than a refusal.
_PLAUSIBLE = {
    "respiratory_rate": (0, 80),
    "spo2": (50, 100),
    "systolic_bp": (30, 300),
    "pulse": (20, 300),
    "temperature": (25.0, 45.0),
}


@dataclass(frozen=True)
class Vitals:
    """One complete set of bedside observations.

    Every field is required: NEWS2 is only valid on a complete observation
    set. A partial score would understate risk, so this refuses to build one.
    """

    respiratory_rate: int          # breaths per minute
    spo2: int                      # oxygen saturation, %
    on_oxygen: bool                # True if receiving supplemental oxygen
    systolic_bp: int               # mmHg
    pulse: int                     # beats per minute
    consciousness: Consciousness
    temperature: float             # degrees Celsius
    spo2_scale: SpO2Scale = SpO2Scale.SCALE_1

    def __post_init__(self) -> None:
        for name in ("respiratory_rate", "spo2", "systolic_bp", "pulse", "temperature"):
            value = getattr(self, name)
            if value is None:
                raise VitalsError(f"{name} is required for a NEWS2 score")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise VitalsError(f"{name} must be numeric, got {value!r}")
            low, high = _PLAUSIBLE[name]
            if not low <= value <= high:
                raise VitalsError(
                    f"{name}={value} is outside the plausible range {low}-{high}; "
                    f"check for a data-entry error"
                )
        if not isinstance(self.consciousness, Consciousness):
            raise VitalsError("consciousness must be a Consciousness value (ACVPU)")
        if not isinstance(self.spo2_scale, SpO2Scale):
            raise VitalsError("spo2_scale must be a SpO2Scale value")
        if not isinstance(self.on_oxygen, bool):
            raise VitalsError("on_oxygen must be a bool")


@dataclass(frozen=True)
class ParameterScore:
    """The score contributed by one parameter, with the reason why."""

    name: str
    value: object
    points: int
    band: str

    def __str__(self) -> str:
        return f"{self.name}={self.value} -> {self.points} ({self.band})"


@dataclass(frozen=True)
class News2Result:
    total: int
    risk: RiskLevel
    parameters: tuple = field(default_factory=tuple)
    has_red_score: bool = False        # any single parameter scoring 3
    recommendation: str = ""

    def breakdown(self) -> str:
        return "\n".join(f"  {p}" for p in self.parameters)


def _band_respiratory_rate(rr: int) -> tuple:
    if rr <= 8:
        return 3, "<=8"
    if rr <= 11:
        return 1, "9-11"
    if rr <= 20:
        return 0, "12-20"
    if rr <= 24:
        return 2, "21-24"
    return 3, ">=25"


def _band_spo2_scale1(spo2: int) -> tuple:
    if spo2 <= 91:
        return 3, "<=91"
    if spo2 <= 93:
        return 2, "92-93"
    if spo2 <= 95:
        return 1, "94-95"
    return 0, ">=96"


def _band_spo2_scale2(spo2: int, on_oxygen: bool) -> tuple:
    """Scale 2: target range 88-92%.

    Above the target range the score only rises when the patient is on
    supplemental oxygen — a high saturation on air is not a concern, but the
    same figure on oxygen means they are being over-oxygenated.
    """
    if spo2 <= 83:
        return 3, "<=83"
    if spo2 <= 85:
        return 2, "84-85"
    if spo2 <= 87:
        return 1, "86-87"
    if spo2 <= 92:
        return 0, "88-92 (target)"
    # spo2 >= 93
    if not on_oxygen:
        return 0, ">=93 on air"
    if spo2 <= 94:
        return 1, "93-94 on oxygen"
    if spo2 <= 96:
        return 2, "95-96 on oxygen"
    return 3, ">=97 on oxygen"


def _band_systolic_bp(sbp: int) -> tuple:
    if sbp <= 90:
        return 3, "<=90"
    if sbp <= 100:
        return 2, "91-100"
    if sbp <= 110:
        return 1, "101-110"
    if sbp <= 219:
        return 0, "111-219"
    return 3, ">=220"


def _band_pulse(pulse: int) -> tuple:
    if pulse <= 40:
        return 3, "<=40"
    if pulse <= 50:
        return 1, "41-50"
    if pulse <= 90:
        return 0, "51-90"
    if pulse <= 110:
        return 1, "91-110"
    if pulse <= 130:
        return 2, "111-130"
    return 3, ">=131"


def _band_temperature(temp: float) -> tuple:
    if temp <= 35.0:
        return 3, "<=35.0"
    if temp <= 36.0:
        return 1, "35.1-36.0"
    if temp <= 38.0:
        return 0, "36.1-38.0"
    if temp <= 39.0:
        return 1, "38.1-39.0"
    return 2, ">=39.1"


def _classify(total: int, has_red_score: bool) -> tuple:
    """Map a total (and the single-parameter-3 rule) to a clinical response.

    The red-score rule matters: a patient scoring 3 on one parameter and 0 on
    everything else totals 3, which by total alone reads as low risk. NEWS2
    escalates that case explicitly.
    """
    if total >= 7:
        return (
            RiskLevel.HIGH,
            "Emergency response. Continuous monitoring. Urgent assessment by a "
            "clinical team with critical-care competencies.",
        )
    if total >= 5:
        return (
            RiskLevel.MEDIUM,
            "Urgent response. Review by a clinician able to escalate to critical "
            "care. Minimum hourly monitoring.",
        )
    if has_red_score:
        return (
            RiskLevel.LOW_MEDIUM,
            "Urgent ward-based review by a clinician, because a single parameter "
            "scores 3 even though the total is low. Minimum hourly monitoring.",
        )
    if total >= 1:
        return (
            RiskLevel.LOW,
            "Ward-based response. Assessment by a competent registered nurse. "
            "Minimum 4-6 hourly monitoring.",
        )
    return (RiskLevel.LOW, "Routine monitoring, minimum 12 hourly.")


def score_vitals(vitals: Vitals) -> News2Result:
    """Compute the NEWS2 score for one complete observation set.

    Returns the total, the clinical risk band, the recommended response, and a
    per-parameter breakdown so a clinician can see exactly where the score came
    from. Explainability is not optional in clinical software.
    """
    if not isinstance(vitals, Vitals):
        raise VitalsError("score_vitals expects a Vitals instance")

    rr_pts, rr_band = _band_respiratory_rate(vitals.respiratory_rate)

    if vitals.spo2_scale is SpO2Scale.SCALE_1:
        spo2_pts, spo2_band = _band_spo2_scale1(vitals.spo2)
    else:
        spo2_pts, spo2_band = _band_spo2_scale2(vitals.spo2, vitals.on_oxygen)

    o2_pts, o2_band = (2, "supplemental oxygen") if vitals.on_oxygen else (0, "air")
    bp_pts, bp_band = _band_systolic_bp(vitals.systolic_bp)
    pulse_pts, pulse_band = _band_pulse(vitals.pulse)
    acvpu_pts, acvpu_band = (
        (0, "alert") if vitals.consciousness is Consciousness.ALERT else (3, "not alert")
    )
    temp_pts, temp_band = _band_temperature(vitals.temperature)

    parameters = (
        ParameterScore("respiratory_rate", vitals.respiratory_rate, rr_pts, rr_band),
        ParameterScore(
            f"spo2 (scale {vitals.spo2_scale.value})", vitals.spo2, spo2_pts, spo2_band
        ),
        ParameterScore("air_or_oxygen", "O2" if vitals.on_oxygen else "air", o2_pts, o2_band),
        ParameterScore("systolic_bp", vitals.systolic_bp, bp_pts, bp_band),
        ParameterScore("pulse", vitals.pulse, pulse_pts, pulse_band),
        ParameterScore("consciousness", vitals.consciousness.value, acvpu_pts, acvpu_band),
        ParameterScore("temperature", vitals.temperature, temp_pts, temp_band),
    )

    total = sum(p.points for p in parameters)
    has_red_score = any(p.points == 3 for p in parameters)
    risk, recommendation = _classify(total, has_red_score)

    return News2Result(
        total=total,
        risk=risk,
        parameters=parameters,
        has_red_score=has_red_score,
        recommendation=recommendation,
    )


if __name__ == "__main__":  # pragma: no cover - manual demo
    demo = Vitals(
        respiratory_rate=22,
        spo2=93,
        on_oxygen=True,
        systolic_bp=105,
        pulse=115,
        consciousness=Consciousness.ALERT,
        temperature=38.5,
    )
    result = score_vitals(demo)
    print(f"NEWS2 total: {result.total}  risk: {result.risk.value}")
    print(f"red score (any parameter = 3): {result.has_red_score}")
    print("breakdown:")
    print(result.breakdown())
    print(f"\n{result.recommendation}")
