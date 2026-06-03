from lead_enrichment.extractors.decision_makers import clean_person_name, extract_decision_maker


def test_clean_person_name_trims_english_research_noise():
    assert clean_person_name("Dennis Stamm. The company's registered address is Mannheim") == "Dennis Stamm"


def test_clean_person_name_trims_tax_and_address_noise():
    assert clean_person_name("HHJ Lesker. Ust-ID NL123 Adresse Venweg 11") == "HHJ Lesker"


def test_clean_person_name_trims_street_and_arbitration_noise():
    assert clean_person_name("Dennis Stamm Werderstr 12") == "Dennis Stamm"
    assert clean_person_name("Frau Andrea Seebacher EU-STREITSCHLICHTUNG Wir") == "Frau Andrea Seebacher"


def test_clean_person_name_trims_long_tax_label():
    assert clean_person_name("Dennis Stamm Umsatzsteuer-Identifikationsnummer DE291475296") == "Dennis Stamm"


def test_extract_decision_maker_from_english_tavily_answer():
    result = extract_decision_maker(
        "Das BilderbuchCafé is a coffee shop. The shop is run by Thomas Friedrich and offers pickup."
    )

    assert result["name"] == "Thomas Friedrich"


def test_extract_decision_maker_rejects_single_word_ceo_answer():
    result = extract_decision_maker(
        "Schul-und-spielzeug.de is operated by Neusser. The company is based in Nußloch."
    )

    assert result["name"] == ""
