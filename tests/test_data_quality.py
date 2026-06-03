from lead_enrichment.data_quality import sanitize_legal_name, sanitize_person_name, sanitize_phone, sanitize_queue_fields


def test_sanitize_phone_removes_known_bad_values():
    assert sanitize_phone("05.2026") == ""
    assert sanitize_phone("0152-0153") == ""
    assert sanitize_phone("049 2.927") == ""
    assert sanitize_phone("09 17.8882 28.7852 17") == ""
    assert sanitize_phone("000 0716 9535") == ""
    assert sanitize_phone("0)664 4024788") == "0664 4024788"
    assert sanitize_phone("039387 592555") == "039387 592555"


def test_sanitize_legal_name_removes_known_false_positives():
    assert sanitize_legal_name("Zammad GmbH") == ""
    assert sanitize_legal_name("box-taped 1 KG") == ""
    assert sanitize_legal_name("Illy Classico espresso 3 KG") == ""
    assert sanitize_legal_name("Diensteanbieter Naturkosmetik-Werkstatt GmbH") == "Naturkosmetik-Werkstatt GmbH"


def test_sanitize_person_name_removes_noise_and_single_word_false_positive():
    assert sanitize_person_name("einer") == ""
    assert sanitize_person_name("Dennis Stamm Werderstr 12") == "Dennis Stamm"
    assert sanitize_person_name("Dennis Stamm Umsatzsteuer-Identifikationsnummer") == "Dennis Stamm"
    assert sanitize_person_name("Frau Andrea Seebacher EU-STREITSCHLICHTUNG Wir") == "Frau Andrea Seebacher"


def test_sanitize_queue_fields_clears_bad_existing_values():
    row = sanitize_queue_fields(
        {
            "phone_main": "05.2026",
            "legal_name": "Zammad GmbH",
            "legal_form": "GmbH",
            "managing_director_name": "einer",
            "managing_director_source": "website_text",
        }
    )

    assert row["phone_main"] == ""
    assert row["legal_name"] == ""
    assert row["legal_form"] == ""
    assert row["managing_director_name"] == ""
    assert row["managing_director_source"] == ""
