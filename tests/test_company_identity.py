from lead_enrichment.extractors.company_identity import (
    clean_company_name,
    company_identity_from_text,
    company_name_from_row,
)


def test_clean_company_name_rejects_low_value_names():
    assert clean_company_name("Impressum") == ""
    assert clean_company_name("Muster GmbH | Impressum") == "Muster GmbH"


def test_company_name_from_row_falls_back_to_domain():
    name, source, confidence = company_name_from_row({"domain": "muster-shop.de", "company_name": ""})

    assert name == "Muster Shop"
    assert source == "derived_from_domain"
    assert confidence == 0.35


def test_company_identity_from_text_detects_legal_form_and_name():
    result = company_identity_from_text("Angaben gemaess Impressum Muster Shop GmbH Adresse Berlin")

    assert result["legal_form"].lower() == "gmbh"
    assert "Muster Shop GmbH" in result["legal_name"]


def test_company_identity_rejects_vendor_and_sentence_false_positives():
    vendor = company_identity_from_text("Newsletter mit CleverReach GmbH & Co. KG. Impressum Muster Shop GmbH")
    zammad = company_identity_from_text("Support wird durch Zammad GmbH bereitgestellt.")
    sentence = company_identity_from_text(
        "Nach drei Seminarraumadaptierungen und einer Umgruendung in eine GmbH folgt der Shop."
    )

    assert vendor["legal_name"] == "Muster Shop GmbH"
    assert zammad["legal_name"] == ""
    assert sentence["legal_name"] == ""


def test_company_identity_rejects_product_quantity_as_kg_legal_form():
    result = company_identity_from_text("Kaffee Online Shop Illy Classico espresso 3 KG jetzt kaufen")

    assert result["legal_name"] == ""
