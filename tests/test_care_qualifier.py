"""Tests for the Pflegebox / Pflegehilfsmittel ICP classification.

These guard the marker sets and scoring logic that decide whether a
verified site is a Pflegebox provider (A++), a weaker provider (A/B),
a ratgeber/content page (Reject), or an unrelated site.

Markers are derived from the six reference providers we analysed
during the fork (pflegemittelbox, sanubi, pflegebox, mein-pflegeset,
box4pflege, hygibox), so the fixtures here mirror the kind of HTML
they all share.
"""

from __future__ import annotations

from care_lead_system.scraper.lead_qualifier import (
    classify_lead_care,
    detect_care_signals,
    detect_ik_number,
    detect_scale_indicators,
    next_action_care,
    score_fit_care,
)


PFLEGEBOX_HTML = """
<html><body>
<h1>Die Pflegebox - kostenlos für gesetzlich Versicherte</h1>
<p>Pflegehilfsmittel zum Verbrauch im Wert von 42 Euro monatlich.</p>
<p>Die Pflegekasse übernimmt die Kosten gemäß § 40 SGB XI für jeden
mit Pflegegrad 1 bis 5.</p>
<p>Wir sind zertifizierter Vertragspartner aller gesetzlichen
Krankenkassen.</p>
<button>Pflegebox beantragen</button>
<button>Pflegebox zusammenstellen</button>
<p>Logos: AOK, DAK, Barmer, IKK Classic, Knappschaft</p>
<p>Über 5.000 Kunden vertrauen uns bundesweit.</p>
<p>Mit über 50 Mitarbeitern für Sie da.</p>
<footer>Impressum: IK-Nummer 123456789</footer>
</body></html>
"""

WEAK_PROVIDER_HTML = """
<html><body>
<h1>Pflegehilfsmittel online bestellen</h1>
<p>Wir bieten Pflegebox-Sets an. Kostenübernahme möglich.</p>
<p>Antrag stellen über unseren Konfigurator.</p>
</body></html>
"""

RATGEBER_HTML = """
<html><body>
<h1>Ratgeber Pflege - Alles wissenswerte</h1>
<p>Ausführlicher Ratgeber zur Pflegeversicherung. Pflegeportal mit
Pflegemagazin und Lexikon.</p>
<p>Informationen für Angehörige. Pflegestützpunkt-Adressen.</p>
<p>Vergleichsportal für Pflegeleistungen.</p>
<p>Stiftung Warentest hat verschiedene Anbieter getestet.</p>
</body></html>
"""

UNRELATED_HTML = """
<html><body>
<h1>Bio Tee aus Hessen</h1>
<p>Wir liefern fairen Tee. Zur Kasse, Versandkosten ab 5 Euro.</p>
</body></html>
"""


# --- detect_ik_number ------------------------------------------------

def test_detect_ik_number_explicit_label() -> None:
    assert detect_ik_number("IK-Nummer: 123456789") == "123456789"
    assert detect_ik_number("IK 123456789") == "123456789"
    assert detect_ik_number("IK Nr. 123456789") == "123456789"
    assert detect_ik_number("IK-Nr.: 123456789") == "123456789"


def test_detect_ik_number_institutionskennzeichen_variants() -> None:
    """Spotted in real imprints: standard and the truncated variant."""
    assert detect_ik_number("Institutionskennzeichen: 123456789") == "123456789"
    # hygibox.de uses this variant
    assert detect_ik_number("Institutskennzeichen: 330556898") == "330556898"


def test_detect_ik_number_nearby_label() -> None:
    """9-digit number near 'IK' label without colon also counts."""
    text = "Wir sind ein Vertragspartner. IK 330556898 ausgestellt 2018."
    assert detect_ik_number(text) == "330556898"


def test_detect_ik_number_ignores_unrelated_9_digit() -> None:
    """USt-IDs and tracking IDs must not be mistaken for IK-Nummer."""
    text = "Umsatzsteuer-Identifikationsnummer DE 274932187. Telefon: 030 12345678."
    assert detect_ik_number(text) == ""


def test_detect_ik_number_empty_on_no_match() -> None:
    assert detect_ik_number("") == ""
    assert detect_ik_number("Some random text without any digits.") == ""


# --- detect_care_signals --------------------------------------------

def test_detect_care_signals_full_provider() -> None:
    signals = detect_care_signals(PFLEGEBOX_HTML, PFLEGEBOX_HTML)
    assert signals["product"], "must find Pflegebox / Pflegehilfsmittel"
    assert signals["gkv"], "must find §40 SGB XI / Pflegekasse / etc."
    assert signals["process"], "must find Antrag / beantragen / etc."
    assert signals["insurers"], "must find AOK / DAK / Barmer / IKK / Knappschaft"
    assert signals["ratgeber"] == [], "must NOT trip the ratgeber filter"


def test_detect_care_signals_ratgeber_page() -> None:
    signals = detect_care_signals(RATGEBER_HTML, RATGEBER_HTML)
    assert len(signals["ratgeber"]) >= 3, "must catch multiple ratgeber markers"
    assert signals["process"] == [], "no provider order flow"


def test_detect_care_signals_empty_for_unrelated_site() -> None:
    signals = detect_care_signals(UNRELATED_HTML, UNRELATED_HTML)
    assert signals["product"] == []
    assert signals["gkv"] == []
    assert signals["process"] == []
    assert signals["insurers"] == []


# --- detect_scale_indicators ----------------------------------------

def test_detect_scale_indicators_picks_kundenzahl() -> None:
    found = detect_scale_indicators("Über 5.000 Kunden vertrauen uns")
    assert any("kunden" in s.lower() for s in found)


def test_detect_scale_indicators_picks_mitarbeiter() -> None:
    found = detect_scale_indicators("Mit über 500 Mitarbeitern für Sie da.")
    assert any("mitarbeiter" in s.lower() for s in found)


def test_detect_scale_indicators_picks_bundesweit() -> None:
    found = detect_scale_indicators("Wir liefern bundesweit nach Hause.")
    assert any("bundesweit" in s.lower() for s in found)


# --- classify_lead_care --------------------------------------------

def test_classify_lead_care_with_ik_and_product_is_anbieter() -> None:
    signals = detect_care_signals(PFLEGEBOX_HTML, PFLEGEBOX_HTML)
    lead_type, reason = classify_lead_care(signals, ik_number="123456789", scale_indicators=[])
    assert lead_type == "pflegebox_anbieter"
    assert reason == ""


def test_classify_lead_care_strong_signals_without_ik_still_anbieter() -> None:
    signals = detect_care_signals(PFLEGEBOX_HTML, PFLEGEBOX_HTML)
    lead_type, _ = classify_lead_care(signals, ik_number="", scale_indicators=[])
    # Multiple product + GKV + process markers compensate for the missing
    # IK so the site still classifies as a real provider.
    assert lead_type == "pflegebox_anbieter"


def test_classify_lead_care_weak_signals_become_review() -> None:
    signals = detect_care_signals(WEAK_PROVIDER_HTML, WEAK_PROVIDER_HTML)
    lead_type, reason = classify_lead_care(signals, ik_number="", scale_indicators=[])
    # Weak page: one product marker plus one process marker but not enough
    # GKV evidence and no IK → must NOT promote to verified provider.
    assert lead_type in {"review", "pflegebox_anbieter"}
    if lead_type == "review":
        assert reason == "weak_care_signals"


def test_classify_lead_care_ratgeber_is_rejected() -> None:
    signals = detect_care_signals(RATGEBER_HTML, RATGEBER_HTML)
    lead_type, reason = classify_lead_care(signals, ik_number="", scale_indicators=[])
    assert lead_type == "ratgeber_site"
    assert reason == "ratgeber_or_content_site"


def test_classify_lead_care_unrelated_is_rejected() -> None:
    signals = detect_care_signals(UNRELATED_HTML, UNRELATED_HTML)
    lead_type, reason = classify_lead_care(signals, ik_number="", scale_indicators=[])
    assert lead_type == "rejected"
    assert reason == "no_care_signals"


# --- score_fit_care ------------------------------------------------

def test_score_fit_care_a_plus_plus_requires_ik_and_scale() -> None:
    signals = detect_care_signals(PFLEGEBOX_HTML, PFLEGEBOX_HTML)
    score = score_fit_care(
        lead_type="pflegebox_anbieter",
        ik_number="123456789",
        care_signals=signals,
        scale_indicators=["5.000 Kunden", "500 Mitarbeiter", "bundesweit"],
        is_dach=True,
        email="info@example.de",
        phone="030 12345678",
    )
    assert score >= 85, f"expected A++ tier (>= 85), got {score}"


def test_score_fit_care_review_lead_clamps_below_60() -> None:
    signals = detect_care_signals(WEAK_PROVIDER_HTML, WEAK_PROVIDER_HTML)
    score = score_fit_care(
        lead_type="review",
        ik_number="123456789",  # even with IK, review clamps
        care_signals=signals,
        scale_indicators=["bundesweit"],
        is_dach=True,
        email="",
        phone="",
    )
    assert score <= 55


def test_score_fit_care_rejected_is_zero() -> None:
    signals = detect_care_signals(RATGEBER_HTML, RATGEBER_HTML)
    assert score_fit_care("ratgeber_site", "", signals, [], True, "", "") == 0
    assert score_fit_care("rejected", "", signals, [], True, "", "") == 0


# --- next_action_care ----------------------------------------------

def test_next_action_care_high_score_with_ik_becomes_loom_candidate() -> None:
    assert next_action_care("pflegebox_anbieter", 90, "123456789") == "loom_candidate"


def test_next_action_care_review_becomes_manual_review() -> None:
    assert next_action_care("review", 40, "") == "manual_review"


def test_next_action_care_ratgeber_becomes_reject() -> None:
    assert next_action_care("ratgeber_site", 0, "") == "reject"
    assert next_action_care("rejected", 0, "") == "reject"


# --- grade_from_care_row -------------------------------------------
# Calibrated against the actual scores we measured live for the six
# reference providers: hygibox=76 (with IK), sanubi=61, box4pflege=55,
# pflegebox=51, mein-pflegeset=45, pflegemittelbox=42 (all without
# published IK). IK is a bonus signal, not a gate, so a provider
# without IK can still reach A or A+ on care signals alone.

import pytest  # noqa: E402

from care_lead_system.verification_adapter import grade_from_care_row, grade_from_verification_row  # noqa: E402


def _care_row(**kwargs):
    base = {
        "niche": "pflegebox",
        "care_lead_type": "pflegebox_anbieter",
    }
    base.update(kwargs)
    return base


def test_grade_from_care_row_a_plus_plus_with_ik_and_high_score() -> None:
    row = _care_row(vhd_fit_score="76", ik_number="330556898")
    assert grade_from_care_row(row) == "A++"


def test_grade_from_care_row_a_plus_at_or_above_60() -> None:
    """sanubi.de hit 61 without published IK and should land in A+."""
    assert grade_from_care_row(_care_row(vhd_fit_score="61")) == "A+"
    assert grade_from_care_row(_care_row(vhd_fit_score="60")) == "A+"


def test_grade_from_care_row_a_for_45_to_59() -> None:
    """pflegebox/box4pflege/mein-pflegeset all sit in this band."""
    for score in (45, 51, 55, 59):
        assert grade_from_care_row(_care_row(vhd_fit_score=str(score))) == "A", f"score {score}"


def test_grade_from_care_row_b_for_30_to_44() -> None:
    """pflegemittelbox sat at 42; must not fall below B."""
    assert grade_from_care_row(_care_row(vhd_fit_score="42")) == "B"
    assert grade_from_care_row(_care_row(vhd_fit_score="30")) == "B"


def test_grade_from_care_row_review_below_30() -> None:
    assert grade_from_care_row(_care_row(vhd_fit_score="20")) == "Review"


def test_grade_from_care_row_review_lead_type_always_review() -> None:
    row = _care_row(care_lead_type="review", vhd_fit_score="40")
    assert grade_from_care_row(row) == "Review"


@pytest.mark.parametrize(
    "care_lead_type,exclusion",
    [
        ("ratgeber_site", "ratgeber_or_content_site"),
        ("rejected", "no_care_signals"),
    ],
)
def test_grade_from_care_row_rejects_non_provider(care_lead_type: str, exclusion: str) -> None:
    row = _care_row(care_lead_type=care_lead_type, vhd_fit_score="0", exclusion_reason=exclusion)
    assert grade_from_care_row(row) == "Reject"


def test_grade_from_care_row_ik_is_not_required_for_a_plus() -> None:
    """Anchor the policy: IK is a bonus, never a gate."""
    row = _care_row(vhd_fit_score="68", ik_number="")
    assert grade_from_care_row(row) == "A+"


def test_grade_from_verification_row_routes_pflegebox_niche_through_care_grading() -> None:
    """The top-level entry point must respect the niche field."""
    care_row = _care_row(vhd_fit_score="76", ik_number="330556898")
    assert grade_from_verification_row(care_row) == "A++"

    # If the row carries the legacy shop classification, the woocommerce
    # grader still applies — guarantees backwards compatibility.
    legacy_row = {
        "vhd_fit_score": "85",
        "is_shop": "yes",
        "is_woocommerce": "yes",
        "detected_platform": "woocommerce",
        "possible_shop_levers": "checkout_payment_shipping_review",
    }
    assert grade_from_verification_row(legacy_row) == "A++"
