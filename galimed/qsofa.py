"""qSOFA — quick Sequential Organ Failure Assessment.

Bedside sepsis-risk screen from the Sepsis-3 consensus definitions, for the
GALIMED AI platform.

WHY THIS REUSES news2's TYPES
-------------------------------
qSOFA and NEWS2 are both read off the same bedside observation set — a
clinician does not take a separate set of vitals for each score. So
score_qsofa() takes a news2.Vitals directly (using only the three fields
qSOFA needs: respiratory_rate, systolic_bp, consciousness) instead of
defining a second, overlapping vitals type. It also reuses
news2.ParameterScore for the breakdown and news2.VitalsError for input
errors, for the same reason NEWS2 and qSOFA share a patient in real life:
one invalid observation set is invalid for every score computed from it.

CLINICAL SAFETY
----------------
qSOFA is a screening aid for sepsis-related risk of poor outcome outside
the ICU. It is NOT a diagnosis of sepsis, and it does not replace clinical
judgement. Critically: qSOFA has known limited sensitivity — a score below
2 does NOT rule out sepsis, and must never be used to stand down a clinical
suspicion of sepsis on its own. It is not validated for pregnancy or for
children under 18. A low score never overrides a clinician's concern.

Reference: Singer M, Deutschman CS, Seymour CW, et al. "The Third
International Consensus Definitions for Sepsis and Septic Shock (Sepsis-3)."
JAMA. 2016;315(8):801-810.

No third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from news2 import Consciousness, ParameterScore, Vitals, VitalsError

__all__ = ["QsofaResult", "score_qsofa"]


@dataclass(frozen=True)
class QsofaResult:
    total: int
    high_risk: bool            # total >= 2
    parameters: tuple = field(default_factory=tuple)
    recommendation: str = ""

    def breakdown(self) -> str:
        return "\n".join(f"  {p}" for p in self.parameters)


_HIGH_RISK_RECOMMENDATION = (
    "qSOFA >= 2: increased risk of sepsis-related mortality. Consider "
    "lactate measurement, blood cultures, and a full SOFA reassessment. "
    "Urgent clinical escalation."
)

_LOW_RISK_RECOMMENDATION = (
    "qSOFA < 2: this does NOT rule out sepsis. qSOFA has limited "
    "sensitivity; if sepsis is clinically suspected, continue the "
    "workup regardless of this score."
)


def score_qsofa(vitals: Vitals) -> QsofaResult:
    """Compute the qSOFA score from a news2.Vitals observation set.

    Uses only respiratory_rate, systolic_bp, and consciousness; the other
    fields on Vitals (spo2, pulse, temperature, ...) are not part of qSOFA
    and are ignored here.
    """
    if not isinstance(vitals, Vitals):
        raise VitalsError("score_qsofa expects a news2.Vitals instance")

    rr_pts, rr_band = (1, ">=22") if vitals.respiratory_rate >= 22 else (0, "<22")
    bp_pts, bp_band = (1, "<=100") if vitals.systolic_bp <= 100 else (0, ">100")
    altered = vitals.consciousness is not Consciousness.ALERT
    mentation_pts, mentation_band = (1, "altered") if altered else (0, "alert")

    parameters = (
        ParameterScore("respiratory_rate", vitals.respiratory_rate, rr_pts, rr_band),
        ParameterScore("systolic_bp", vitals.systolic_bp, bp_pts, bp_band),
        ParameterScore("consciousness", vitals.consciousness.value, mentation_pts, mentation_band),
    )

    total = sum(p.points for p in parameters)
    high_risk = total >= 2
    recommendation = _HIGH_RISK_RECOMMENDATION if high_risk else _LOW_RISK_RECOMMENDATION

    return QsofaResult(total=total, high_risk=high_risk, parameters=parameters, recommendation=recommendation)


if __name__ == "__main__":  # pragma: no cover - manual demo
    demo = Vitals(
        respiratory_rate=24,
        spo2=93,
        on_oxygen=True,
        systolic_bp=95,
        pulse=115,
        consciousness=Consciousness.CONFUSION,
        temperature=38.9,
    )
    result = score_qsofa(demo)
    print(f"qSOFA total: {result.total}  high_risk: {result.high_risk}")
    print(result.breakdown())
    print(f"\n{result.recommendation}")
