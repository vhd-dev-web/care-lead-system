from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    status: str
    do_not_contact: bool
    reason: str
    next_action: str


def assess_outreach_gate(
    *,
    priority: str,
    has_phone: bool,
    has_personal_email: bool,
    has_b2b_context: bool,
    has_concrete_angle: bool,
    has_do_not_contact_signal: bool = False,
) -> GateResult:
    if has_do_not_contact_signal or priority == "Reject":
        return GateResult(
            status="do_not_contact",
            do_not_contact=True,
            reason="Lead is rejected, excluded, or has a do-not-contact signal.",
            next_action="do_not_contact",
        )
    if not has_b2b_context:
        return GateResult(
            status="do_not_contact",
            do_not_contact=True,
            reason="B2B/shop context is not sufficiently clear.",
            next_action="do_not_contact",
        )
    if has_personal_email:
        return GateResult(
            status="manual_review",
            do_not_contact=False,
            reason="Personal email present; manual legal and relevance review required before use.",
            next_action="manual_review",
        )
    if priority in {"A", "B"} and has_phone and has_concrete_angle:
        return GateResult(
            status="outreach_ready",
            do_not_contact=False,
            reason="A/B lead with concrete shop relevance and phone-first channel.",
            next_action="manual_call_review",
        )
    return GateResult(
        status="manual_review",
        do_not_contact=False,
        reason="Lead needs manual review before outreach readiness.",
        next_action="manual_review",
    )
