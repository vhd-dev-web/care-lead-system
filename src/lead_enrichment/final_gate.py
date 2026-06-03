from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .compliance.gdpr import gdpr_note
from .compliance.uwg import mutmassliche_einwilligung_reason
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .normalizer import bool_string, clean_text, normalize_domain, truthy
from .queue import QUEUE_FIELDS
from .quality import is_enrichment_worthy, quality_rank


VERIFIED_EMAIL_STATUSES = {"verified", "valid", "deliverable"}
FINAL_FIELDS = QUEUE_FIELDS


@dataclass(frozen=True)
class FinalGateOptions:
    queue_path: Path
    output_dir: Path = Path("data/output")
    clay_results_path: Path | None = None


@dataclass(frozen=True)
class FinalGateResult:
    enriched_path: str
    compliance_review_path: str
    review_path: str
    outreach_ready_path: str
    do_not_contact_path: str
    instantly_ready_path: str
    run_path: str
    row_count: int
    review_count: int
    outreach_ready_count: int
    do_not_contact_count: int
    instantly_ready_count: int


def run_final_gate(options: FinalGateOptions) -> FinalGateResult:
    rows = [ensure_row(row) for row in read_csv_rows(options.queue_path)]
    if options.clay_results_path and options.clay_results_path.exists():
        rows = apply_clay_results(rows, read_csv_rows(options.clay_results_path))

    finalized = [finalize_row(row) for row in rows]
    review_rows = [row for row in finalized if row["compliance_status"] == "manual_review"]
    outreach_rows = [row for row in finalized if row["compliance_status"] == "outreach_ready"]
    dnc_rows = [row for row in finalized if row["compliance_status"] == "do_not_contact"]
    instantly_rows = [row for row in finalized if is_instantly_ready(row)]
    timestamp = now_utc()

    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    enriched_path = output_dir / "enriched_master.csv"
    compliance_review_path = output_dir / "compliance_review.csv"
    review_path = output_dir / "enrichment_review.csv"
    outreach_ready_path = output_dir / "outreach_ready.csv"
    do_not_contact_path = output_dir / "do_not_contact.csv"
    instantly_ready_path = output_dir / "instantly_ready.csv"
    run_path = run_dir / f"final_gate_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, finalized, FINAL_FIELDS)
    write_csv_rows(compliance_review_path, finalized, FINAL_FIELDS)
    write_csv_rows(review_path, review_rows, FINAL_FIELDS)
    write_csv_rows(outreach_ready_path, outreach_rows, FINAL_FIELDS)
    write_csv_rows(do_not_contact_path, dnc_rows, FINAL_FIELDS)
    write_csv_rows(instantly_ready_path, instantly_rows, FINAL_FIELDS)
    write_csv_rows(run_path, finalized, FINAL_FIELDS)

    return FinalGateResult(
        enriched_path=str(enriched_path),
        compliance_review_path=str(compliance_review_path),
        review_path=str(review_path),
        outreach_ready_path=str(outreach_ready_path),
        do_not_contact_path=str(do_not_contact_path),
        instantly_ready_path=str(instantly_ready_path),
        run_path=str(run_path),
        row_count=len(finalized),
        review_count=len(review_rows),
        outreach_ready_count=len(outreach_rows),
        do_not_contact_count=len(dnc_rows),
        instantly_ready_count=len(instantly_rows),
    )


def finalize_row(row: dict[str, str]) -> dict[str, str]:
    finalized = ensure_row(row)
    channel = finalized.get("outreach_channel") or recommend_outreach_channel(finalized)
    finalized["recommended_outreach_channel"] = finalized.get("recommended_outreach_channel") or channel
    finalized["outreach_channel"] = channel
    finalized["gdpr_legal_basis_note"] = finalized.get("gdpr_legal_basis_note") or gdpr_note(
        has_personal_data=bool(finalized.get("managing_director_name") or finalized.get("personal_email")),
        purpose="B2B lead enrichment and manual outreach review",
    )
    finalized["mutmassliche_einwilligung_reason"] = finalized.get(
        "mutmassliche_einwilligung_reason"
    ) or build_uwg_reason(finalized, channel)
    finalized["unsubscribe_required"] = bool_string(channel == "email" or bool(finalized.get("personal_email")))

    status, reason = assess_final_status(finalized)
    finalized["compliance_status"] = status
    finalized["compliance_reason"] = reason
    finalized["do_not_contact"] = bool_string(status == "do_not_contact")
    finalized["do_not_contact_reason"] = reason if status == "do_not_contact" else ""
    finalized["next_action"] = next_action(finalized)
    finalized["instantly_pushed"] = bool_string(truthy(finalized.get("instantly_pushed")))
    return finalized


def assess_final_status(row: dict[str, str]) -> tuple[str, str]:
    if truthy(row.get("do_not_contact")):
        return "do_not_contact", row.get("do_not_contact_reason") or "Lead is marked do-not-contact."
    if not has_b2b_shop_context(row):
        return "do_not_contact", "B2B/shop context is not sufficiently clear."
    if not is_enrichment_worthy(row.get("lead_quality", "")):
        return "do_not_contact", "Lead quality is below enrichment threshold."
    if provider_step_pending(row):
        return "manual_review", "Provider or manual enrichment step is still pending."
    if confidence_score(row) < 0.70:
        return "manual_review", "Source confidence is below 0.70; manual evidence review required."
    if not has_concrete_angle(row):
        return "manual_review", "Concrete WooCommerce/shop relevance note is missing."
    if row.get("personal_email") and not is_instantly_ready(row):
        return "manual_review", "Personal email is present; explicit approval and verified status are required."
    if row.get("phone_main"):
        return "outreach_ready", "Phone-first outreach review is ready with concrete B2B relevance."
    if row.get("linkedin_person_url"):
        return "outreach_ready", "Manual LinkedIn outreach review is ready with concrete B2B relevance."
    if is_instantly_ready(row):
        return "outreach_ready", "Email export is explicitly approved and verified for manual upload."
    return "manual_review", "No conservative contact channel is ready."


def provider_step_pending(row: dict[str, str]) -> bool:
    step = row.get("next_enrichment_step", "")
    provider = row.get("provider_recommended", "")
    if step in {"", "compliance_review", "manual_review", "store_only"}:
        return False
    if step.startswith("clay_email_queue") and not row.get("personal_email"):
        return True
    if step.startswith("clay_email_queue") and row.get("personal_email"):
        return False
    if step.endswith("_planned"):
        return True
    return provider in {"serper", "firecrawl", "tavily", "clay"}


def is_instantly_ready(row: dict[str, str]) -> bool:
    return (
        truthy(row.get("outreach_approved"))
        and not truthy(row.get("do_not_contact"))
        and (row.get("outreach_channel") or row.get("recommended_outreach_channel")) == "email"
        and valid_email(row.get("personal_email"))
        and clean_text(row.get("email_verification_status")).lower() in VERIFIED_EMAIL_STATUSES
    )


def recommend_outreach_channel(row: dict[str, str]) -> str:
    if row.get("personal_email") and truthy(row.get("outreach_approved")):
        return "email"
    if row.get("phone_main"):
        return "call"
    if row.get("linkedin_person_url"):
        return "linkedin"
    if row.get("general_email"):
        return "manual_review"
    return "manual_review"


def build_uwg_reason(row: dict[str, str], channel: str) -> str:
    priority = priority_for_uwg(row.get("lead_quality", ""))
    reason = mutmassliche_einwilligung_reason(
        priority=priority,
        outreach_angle=row.get("why_relevant") or row.get("pain_summary"),
        channel=channel,
        is_woocommerce=truthy(row.get("is_woocommerce")),
    )
    if reason:
        return reason
    return "Not ready for outreach; manual relevance, channel, and legal-basis review required."


def priority_for_uwg(quality: str) -> str:
    if quality_rank(quality) >= quality_rank("A"):
        return "A"
    if quality_rank(quality) >= quality_rank("B"):
        return "B"
    return "C"


def has_b2b_shop_context(row: dict[str, str]) -> bool:
    return (
        truthy(row.get("is_shop"))
        or truthy(row.get("is_woocommerce"))
        or quality_rank(row.get("lead_quality", "")) >= quality_rank("A")
    )


def has_concrete_angle(row: dict[str, str]) -> bool:
    return bool(row.get("why_relevant") or row.get("pain_summary") or row.get("outreach_angle"))


def confidence_score(row: dict[str, str]) -> float:
    for key in ("confidence_score", "firecrawl_confidence_score", "serper_confidence_score", "tavily_confidence_score"):
        value = clean_text(row.get(key))
        if not value:
            continue
        try:
            score = float(value.replace(",", "."))
        except ValueError:
            continue
        if score > 1:
            score /= 100
        return max(0.0, min(1.0, score))
    return 1.0


def next_action(row: dict[str, str]) -> str:
    if row["compliance_status"] == "do_not_contact":
        return "do_not_contact"
    if is_instantly_ready(row):
        return "manual_instantly_upload"
    if row["compliance_status"] == "outreach_ready" and row.get("outreach_channel") == "call":
        return "manual_call_review"
    if row["compliance_status"] == "outreach_ready" and row.get("outreach_channel") == "linkedin":
        return "manual_linkedin_review"
    return "manual_compliance_review"


def apply_clay_results(
    rows: list[dict[str, str]],
    clay_results: list[dict[str, str]],
) -> list[dict[str, str]]:
    by_key = index_clay_results(clay_results)
    updated_rows: list[dict[str, str]] = []
    for row in rows:
        updated = ensure_row(row)
        result = by_key.get(updated.get("lead_id")) or by_key.get(normalize_domain(updated.get("domain")))
        if result:
            merge_clay_result(updated, result)
        updated_rows.append(updated)
    return updated_rows


def index_clay_results(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        normalized = {key: clean_text(value) for key, value in row.items()}
        lead_id = normalized.get("lead_id")
        domain = normalize_domain(normalized.get("domain"))
        if lead_id:
            indexed[lead_id] = normalized
        if domain:
            indexed[domain] = normalized
    return indexed


def merge_clay_result(row: dict[str, str], clay_result: dict[str, str]) -> None:
    email = clean_text(
        clay_result.get("personal_email")
        or clay_result.get("email_personal")
        or clay_result.get("email")
    ).lower()
    status = clean_text(
        clay_result.get("email_verification_status")
        or clay_result.get("verification_status")
        or clay_result.get("status")
    ).lower()
    if email and valid_email(email):
        row["personal_email"] = email
    if status:
        row["email_verification_status"] = status
    row["email_source"] = clean_text(clay_result.get("email_source")) or "clay_manual_import"
    row["clay_used"] = bool_string(True)
    row["clay_eligible"] = bool_string(False)
    row["clay_reason"] = "Clay result imported; manual compliance approval still required."


def valid_email(value: str | None) -> bool:
    email = clean_text(value)
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        return False
    return " " not in email


def ensure_row(row: dict[str, str]) -> dict[str, str]:
    return {field: clean_text(row.get(field)) for field in FINAL_FIELDS}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
