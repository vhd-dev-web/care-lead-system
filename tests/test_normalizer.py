from lead_enrichment.normalizer import normalize_domain, normalize_url, split_tokens, stable_lead_id


def test_normalize_domain_removes_scheme_www_path_and_port():
    assert normalize_domain("https://www.Example-Shop.de/kontakt?x=1") == "example-shop.de"
    assert normalize_domain("example-shop.de:443/path") == "example-shop.de"


def test_normalize_url_prefers_https_and_keeps_path():
    assert normalize_url("www.example-shop.de/impressum") == "https://example-shop.de/impressum"


def test_stable_lead_id_is_domain_based():
    assert stable_lead_id("https://www.example.de/foo") == stable_lead_id("example.de")


def test_split_tokens_accepts_multiple_delimiters():
    assert split_tokens("checkout|tracking, WooCommerce; GTM") == [
        "checkout",
        "tracking",
        "woocommerce",
        "gtm",
    ]
