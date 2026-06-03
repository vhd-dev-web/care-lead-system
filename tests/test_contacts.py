from lead_enrichment.extractors.contacts import (
    choose_general_email,
    choose_main_phone,
    is_generic_email,
    normalize_phone,
)


def test_choose_general_email_prefers_generic_address():
    text = "Kontakt: max.mustermann@example.de oder info@example.de"

    assert choose_general_email(text) == "info@example.de"


def test_generic_email_classifier():
    assert is_generic_email("kontakt@shop.de")
    assert not is_generic_email("max.mustermann@shop.de")


def test_choose_main_phone_extracts_german_number():
    assert choose_main_phone("Telefon +49 30 1234567") == "+49 30 1234567"


def test_choose_main_phone_ignores_dates_and_prefers_phone_context():
    text = "Stand 05.2026. Telefon: +49 221 12345678. Umsatzsteuer-ID DE123"

    assert choose_main_phone(text) == "+49 221 12345678"


def test_choose_main_phone_rejects_bad_short_or_coordinate_like_values():
    assert choose_main_phone("Telefon 0152-0153") == ""
    assert choose_main_phone("Tel. 09 17.8882 28.7852 17") == ""


def test_phone_normalization_repairs_unmatched_optional_zero():
    assert normalize_phone("0)664 4024788") == "0664 4024788"
    assert choose_main_phone("Telefon: 0)664 4024788") == "0664 4024788"


def test_choose_main_phone_rejects_triple_zero_fragment():
    assert choose_main_phone("Telefon: 000 0716 9535") == ""
