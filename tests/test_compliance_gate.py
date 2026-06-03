from lead_enrichment.compliance.outreach_gate import assess_outreach_gate


def test_outreach_ready_requires_ab_priority_phone_and_angle():
    result = assess_outreach_gate(
        priority="A",
        has_phone=True,
        has_personal_email=False,
        has_b2b_context=True,
        has_concrete_angle=True,
    )

    assert result.status == "outreach_ready"
    assert not result.do_not_contact


def test_personal_email_forces_manual_review():
    result = assess_outreach_gate(
        priority="A",
        has_phone=True,
        has_personal_email=True,
        has_b2b_context=True,
        has_concrete_angle=True,
    )

    assert result.status == "manual_review"


def test_reject_priority_is_do_not_contact():
    result = assess_outreach_gate(
        priority="Reject",
        has_phone=True,
        has_personal_email=False,
        has_b2b_context=True,
        has_concrete_angle=True,
    )

    assert result.status == "do_not_contact"
    assert result.do_not_contact
