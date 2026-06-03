from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .compliance.gdpr import gdpr_note
from .compliance.outreach_gate import assess_outreach_gate
from .compliance.uwg import mutmassliche_einwilligung_reason
from .dedupe import dedupe_rows
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.company_identity import company_identity_from_text, company_name_from_row
from .extractors.contacts import choose_general_email, choose_main_phone
from .extractors.decision_makers import extract_decision_maker
from .extractors.technology import detect_woocommerce, detect_wordpress
from .models import EnrichedLead, EnrichmentResult, OUT_FIELDS
from .normalizer import bool_string, clean_text, normalize_domain, normalize_url, stable_lead_id, truthy
from .scoring import (
    build_outreach_angle,
    derive_scores,
    desired_decision_maker_role,
    technology_stack,
)
from .sources.contact_page import discover_contact_url
from .sources.imprint import discover_imprint_url
from .sources.website import fetch_url, html_to_text


@dataclass(frozen=True)
class EnrichmentOptions:
    input_path: Path
    output_dir: Path = Path("data/output")
    mode: str = "csv-only"
    limit: int | None = None
    website_pages_per_domain: int = 3
    user_agent: str = "VHDLeadEnrichment/0.1 (+https://www.vhd-coaching-x2.de/)"


def run_enrichment(options: EnrichmentOptions) -> EnrichmentResult:
    rows = dedupe_rows(read_csv_rows(options.input_path))
    if options.limit is not None:
        rows = rows[: options.limit]

    timestamp = timestamp_utc()
    output_dir = options.output_dir
    run_dir = output_dir / "runs"
    log_dir = output_dir / "logs"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    enriched = [enrich_row(row, options, timestamp) for row in rows]
    enriched_rows = [lead.to_row() for lead in enriched]
    review_rows = [
        lead.to_row()
        for lead in enriched
        if lead.compliance_status == "manual_review"
    ]
    outreach_rows = [
        lead.to_row()
        for lead in enriched
        if lead.compliance_status == "outreach_ready"
    ]

    enriched_path = output_dir / "enriched_master.csv"
    review_path = output_dir / "enrichment_review.csv"
    outreach_ready_path = output_dir / "outreach_ready.csv"
    run_path = run_dir / f"enrichment_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, enriched_rows, OUT_FIELDS)
    write_csv_rows(review_path, review_rows, OUT_FIELDS)
    write_csv_rows(outreach_ready_path, outreach_rows, OUT_FIELDS)
    write_csv_rows(run_path, enriched_rows, OUT_FIELDS)

    return EnrichmentResult(
        rows=enriched,
        enriched_path=str(enriched_path),
        review_path=str(review_path),
        outreach_ready_path=str(outreach_ready_path),
        run_path=str(run_path),
    )


def enrich_row(row: dict[str, str], options: EnrichmentOptions, timestamp: str) -> EnrichedLead:
    domain = normalize_domain(row.get("domain") or row.get("source_url") or row.get("url"))
    website_url = normalize_url(row.get("source_url") or row.get("url"), domain)
    company_name, company_source, company_confidence = company_name_from_row(row)
    scores = derive_scores(row)
    priority = str(scores["overall_priority"])
    outreach_angle = build_outreach_angle(row)
    desired_role = desired_decision_maker_role({"overall_priority": priority, **row})
    woocommerce = detect_woocommerce(row)
    wordpress = detect_wordpress(row)

    email_general = clean_text(row.get("email"))
    phone_main = clean_text(row.get("phone"))
    phone_source = "input_csv:phone" if phone_main else ""
    email_source = "input_csv:email" if email_general else ""
    legal_name = ""
    legal_form = ""
    imprint_url = ""
    contact_form_url = ""
    managing_director = ""
    owner_name = ""
    decision_source = ""
    decision_confidence = ""

    if options.mode == "website" and priority in {"A", "B"} and domain:
        website_fields = enrich_from_website(domain, options)
        if website_fields.get("company_name") and float(company_confidence) < 0.95:
            company_name = website_fields["company_name"]
            company_source = website_fields.get("company_name_source", "website")
            company_confidence = float(website_fields.get("company_name_confidence", "0.85"))
        legal_name = website_fields.get("legal_name", "")
        legal_form = website_fields.get("legal_form", "")
        imprint_url = website_fields.get("imprint_url", "")
        contact_form_url = website_fields.get("contact_form_url", "")
        if not email_general:
            email_general = website_fields.get("email_general", "")
            email_source = website_fields.get("email_general_source", "")
        if not phone_main:
            phone_main = website_fields.get("phone_main", "")
            phone_source = website_fields.get("phone_main_source", "")
        managing_director = website_fields.get("managing_director", "")
        owner_name = website_fields.get("owner_name", "")
        decision_source = website_fields.get("decision_maker_source", "")
        decision_confidence = website_fields.get("decision_maker_confidence", "")

    recommended_channel = recommend_channel(priority, phone_main, email_general)
    has_personal_email = False
    has_b2b_context = priority in {"A", "B", "C", "Review"} and priority != "Reject"
    has_concrete_angle = bool(outreach_angle and priority in {"A", "B"})
    gate = assess_outreach_gate(
        priority=priority,
        has_phone=bool(phone_main),
        has_personal_email=has_personal_email,
        has_b2b_context=has_b2b_context,
        has_concrete_angle=has_concrete_angle,
        has_do_not_contact_signal=bool(row.get("exclusion_reason")),
    )
    mut_reason = mutmassliche_einwilligung_reason(
        priority=priority,
        outreach_angle=outreach_angle,
        channel=recommended_channel,
        is_woocommerce=woocommerce,
    )
    if gate.status != "outreach_ready" and not mut_reason:
        mut_reason = "Not ready for outreach; manual relevance and channel review required."

    lead = EnrichedLead(
        lead_id=stable_lead_id(domain),
        domain=domain,
        website_url=website_url,
        company_name=company_name,
        company_name_source=company_source,
        company_name_confidence=format_confidence(company_confidence),
        legal_name=legal_name,
        legal_form=legal_form,
        country=country_from_row(row),
        imprint_url=imprint_url,
        managing_director=managing_director,
        owner_name=owner_name,
        decision_maker_1_name=managing_director or owner_name,
        decision_maker_1_role="Geschaeftsfuehrer" if managing_director else ("Inhaber" if owner_name else desired_role),
        decision_maker_1_source=decision_source,
        decision_maker_1_confidence=decision_confidence,
        phone_main=phone_main,
        phone_main_source=phone_source,
        email_general=email_general,
        email_general_source=email_source,
        contact_form_url=contact_form_url,
        technology_stack=technology_stack(row),
        woocommerce_detected=bool_string(woocommerce),
        wordpress_detected=bool_string(wordpress),
        shop_relevance_score=str(scores["shop_relevance_score"]),
        technical_pain_score=str(scores["technical_pain_score"]),
        conversion_pain_score=str(scores["conversion_pain_score"]),
        business_potential_score=str(scores["business_potential_score"]),
        overall_priority=priority,
        recommended_outreach_channel=recommended_channel,
        outreach_angle=outreach_angle,
        mutmassliche_einwilligung_reason=mut_reason,
        gdpr_legal_basis_note=gdpr_note(bool(managing_director or owner_name)),
        compliance_status=gate.status,
        do_not_contact=bool_string(gate.do_not_contact),
        do_not_contact_reason=gate.reason if gate.do_not_contact else "",
        last_enriched_at=timestamp,
        next_action=gate.next_action,
        notes=build_notes(row, gate.reason),
    )
    return lead


def enrich_from_website(domain: str, options: EnrichmentOptions) -> dict[str, str]:
    homepage = fetch_url(f"https://{domain}/", user_agent=options.user_agent)
    homepage_text = html_to_text(homepage.html)
    imprint_url = discover_imprint_url(domain, homepage.html)
    contact_url = discover_contact_url(domain, homepage.html)

    pages = [homepage]
    for url in [imprint_url, contact_url]:
        if len(pages) >= options.website_pages_per_domain:
            break
        if url and all(page.url != url for page in pages):
            pages.append(fetch_url(url, user_agent=options.user_agent))

    combined_html = " ".join(page.html for page in pages if page.html)
    combined_text = " ".join([homepage_text] + [html_to_text(page.html) for page in pages[1:]])
    identity = company_identity_from_text(combined_text)
    decision = extract_decision_maker(combined_text)
    managing_director = decision["name"] if decision["role"] == "Geschaeftsfuehrer" else ""
    owner = decision["name"] if decision["role"] == "Inhaber" else ""
    legal_name = identity.get("legal_name", "")

    return {
        "company_name": legal_name,
        "company_name_source": "website_imprint",
        "company_name_confidence": "0.95" if legal_name else "0.0",
        "legal_name": legal_name,
        "legal_form": identity.get("legal_form", ""),
        "imprint_url": imprint_url,
        "contact_form_url": contact_url,
        "email_general": choose_general_email(combined_text),
        "email_general_source": "website_public_page",
        "phone_main": choose_main_phone(combined_text),
        "phone_main_source": "website_public_page",
        "managing_director": str(managing_director),
        "owner_name": str(owner),
        "decision_maker_source": str(decision["source"]),
        "decision_maker_confidence": format_confidence(float(decision["confidence"])),
        "html": combined_html,
    }


def recommend_channel(priority: str, phone: str, email: str) -> str:
    if priority in {"A", "B"} and phone:
        return "phone_main"
    if priority in {"A", "B"}:
        return "manual_linkedin_research"
    if email:
        return "manual_review_generic_email_only"
    return "manual_review"


def country_from_row(row: dict[str, str]) -> str:
    for key in ("country", "country_hint"):
        value = clean_text(row.get(key))
        if value:
            return value.upper()
    if truthy(row.get("is_dach")):
        return "DACH"
    return ""


def build_notes(row: dict[str, str], gate_reason: str) -> str:
    notes = [clean_text(row.get("notes")), gate_reason]
    source_levers = clean_text(row.get("possible_shop_levers"))
    if source_levers:
        notes.append(f"source_levers={source_levers}")
    return " | ".join(note for note in notes if note)


def format_confidence(value: float | str) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
