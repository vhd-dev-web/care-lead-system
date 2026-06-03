from __future__ import annotations

import argparse
from pathlib import Path

from .io_utils import read_table
from .master_updater import MasterUpdater, first_value
from .normalizer import bool_string, normalize_domain, truthy, utc_now
from .run_registry import RunRegistry


ENRICHMENT_ALIASES = {
    "lead_id": ("lead_id",),
    "domain_key": ("domain_key", "domain", "website_url", "source_url", "url"),
    "company_name": ("company_name",),
    "country": ("country",),
    "legal_name": ("legal_name",),
    "legal_name_source": ("legal_name_source", "company_name_source"),
    "legal_name_confidence": ("legal_name_confidence", "company_name_confidence", "confidence_score"),
    "imprint_url": ("imprint_url",),
    "imprint_url_source": ("imprint_url_source", "free_enrichment_source_urls"),
    "imprint_url_confidence": ("imprint_url_confidence", "confidence_score"),
    "email_general": ("email_general", "general_email", "email"),
    "email_general_source": ("email_general_source", "email_source"),
    "email_general_confidence": ("email_general_confidence", "confidence_score"),
    "phone_main": ("phone_main", "phone"),
    "phone_main_source": ("phone_main_source",),
    "phone_main_confidence": ("phone_main_confidence", "confidence_score"),
    "decision_maker_1_name": (
        "decision_maker_1_name",
        "managing_director_name",
        "managing_director",
        "owner_name",
    ),
    "decision_maker_1_role": ("decision_maker_1_role",),
    "decision_maker_1_source": ("decision_maker_1_source", "managing_director_source"),
    "decision_maker_1_confidence": ("decision_maker_1_confidence", "confidence_score"),
    "linkedin_company_url": ("linkedin_company_url",),
    "linkedin_person_url": ("linkedin_person_url",),
    "shop_relevance_score": ("shop_relevance_score",),
    "technical_pain_score": ("technical_pain_score",),
    "conversion_pain_score": ("conversion_pain_score",),
    "business_potential_score": ("business_potential_score", "vhd_fit_score"),
    "lead_grade": ("lead_grade", "overall_priority", "lead_quality"),
    "lead_grade_reason": ("lead_grade_reason", "why_relevant", "pain_summary", "possible_shop_levers"),
    "recommended_outreach_channel": ("recommended_outreach_channel", "outreach_channel"),
    "outreach_angle": ("outreach_angle", "pain_summary", "why_relevant"),
    "next_action": ("next_action", "next_enrichment_step"),
    "next_action_reason": ("next_action_reason", "waterfall_reason", "compliance_reason"),
    "review_reason": ("review_reason", "compliance_reason", "waterfall_reason"),
    "do_not_contact": ("do_not_contact",),
    "do_not_contact_reason": ("do_not_contact_reason",),
    "clay_needed": ("clay_needed", "clay_eligible"),
    "clay_reason": ("clay_reason",),
    "clay_status": ("clay_status",),
    "clay_notes": ("clay_notes",),
}


def build_enrichment_patch(row: dict[str, object]) -> dict[str, str]:
    patch = {field: first_value(row, aliases) for field, aliases in ENRICHMENT_ALIASES.items()}
    patch["domain_key"] = normalize_domain(patch.get("domain_key"))
    checked_at = first_value(row, ("last_enriched_at", "last_queued_at", "checked_at")) or utc_now()
    for field in (
        "legal_name",
        "imprint_url",
        "email_general",
        "phone_main",
        "decision_maker_1_name",
        "linkedin_company_url",
        "linkedin_person_url",
    ):
        if patch.get(field):
            if not patch.get(f"{field}_source"):
                patch[f"{field}_source"] = default_source_for(field, row)
            if not patch.get(f"{field}_confidence"):
                patch[f"{field}_confidence"] = first_value(row, ("confidence_score",)) or "0.70"
            if not patch.get(f"{field}_checked_at"):
                patch[f"{field}_checked_at"] = checked_at
    if patch.get("decision_maker_1_name") and not patch.get("decision_maker_1_role"):
        patch["decision_maker_1_role"] = role_from_enrichment_row(row)
    if patch.get("decision_maker_1_role"):
        if not patch.get("decision_maker_1_source"):
            patch["decision_maker_1_source"] = default_source_for("decision_maker_1_name", row)
        if not patch.get("decision_maker_1_confidence"):
            patch["decision_maker_1_confidence"] = first_value(row, ("confidence_score",)) or "0.70"
        if not patch.get("decision_maker_1_checked_at"):
            patch["decision_maker_1_checked_at"] = checked_at
    if patch.get("lead_grade") in {"Review"} or first_value(row, ("compliance_status",)) == "manual_review":
        patch["manual_review_required"] = "true"
        patch["review_status"] = "manual_review"
    if truthy(patch.get("do_not_contact")):
        patch["pipeline_status"] = "do_not_contact"
        patch["review_status"] = "do_not_contact"
    else:
        patch["pipeline_status"] = "enriched"
    patch["enrichment_stage"] = stage_from_enrichment_row(row)
    patch["last_completed_step"] = "enrichment"
    patch["last_completed_at"] = checked_at
    add_provider_statuses(patch, row, checked_at)
    if truthy(patch.get("clay_needed")) and not patch.get("clay_status"):
        patch["clay_status"] = "needed"
    return {key: value for key, value in patch.items() if value}


def default_source_for(field: str, row: dict[str, object]) -> str:
    if field == "email_general":
        return first_value(row, ("email_general_source", "email_source")) or "vhd-lead-enrichment"
    if field == "phone_main":
        return first_value(row, ("phone_main_source",)) or "vhd-lead-enrichment"
    if field == "decision_maker_1_name":
        return first_value(row, ("decision_maker_1_source", "managing_director_source")) or "vhd-lead-enrichment"
    return first_value(row, (f"{field}_source",)) or "vhd-lead-enrichment"


def role_from_enrichment_row(row: dict[str, object]) -> str:
    if first_value(row, ("managing_director", "managing_director_name")):
        return "Geschaeftsfuehrer"
    if first_value(row, ("owner_name",)):
        return "Inhaber"
    return ""


def stage_from_enrichment_row(row: dict[str, object]) -> str:
    step = first_value(row, ("next_enrichment_step", "next_action"))
    if step.startswith("clay_email_queue"):
        return "clay_handoff_ready"
    status = first_value(row, ("enrichment_status", "compliance_status"))
    if status:
        return status
    return "enriched"


def add_provider_statuses(patch: dict[str, str], row: dict[str, object], checked_at: str) -> None:
    providers = {
        "firecrawl": truthy(first_value(row, ("firecrawl_used",))),
        "serper": truthy(first_value(row, ("serper_used",))),
        "tavily": truthy(first_value(row, ("tavily_used",))),
    }
    recommended = first_value(row, ("provider_recommended",))
    for provider, used in providers.items():
        error = first_value(row, (f"{provider}_error",))
        if used:
            patch[f"{provider}_needed"] = "false"
            patch[f"{provider}_status"] = "done"
            patch[f"{provider}_checked_at"] = checked_at
        elif error:
            patch[f"{provider}_needed"] = "true"
            patch[f"{provider}_status"] = "failed"
            patch[f"{provider}_error"] = error
            patch[f"{provider}_checked_at"] = checked_at
        elif recommended == provider:
            patch[f"{provider}_needed"] = "true"
            patch[f"{provider}_status"] = "needed"
            patch[f"{provider}_reason"] = first_value(row, ("waterfall_reason", "research_note"))


def import_enrichment_results(path: str | Path, *, root_dir: str | Path = ".") -> dict[str, object]:
    rows = read_table(path)
    patches = [build_enrichment_patch(row) for row in rows]
    registry = RunRegistry(root_dir)
    run = registry.start_run("enrichment_import", input_paths=[str(path)])
    updater = MasterUpdater(root_dir)
    try:
        created_result = updater.upsert_scrape_rows(rows, source_name=Path(path).stem, run_id=run.run_id)
        result = updater.update_leads(patches, run_id=run.run_id, step="enrichment", match_key="domain_key")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[str(updater.store.master_csv_path)],
            records_read=result.records_read,
            records_written=created_result.records_created + result.records_updated,
            records_created=created_result.records_created,
            records_updated=result.records_updated,
            records_skipped=created_result.records_skipped + result.records_skipped,
        )
        return {
            "run_id": run.run_id,
            "records_read": result.records_read,
            "records_created": created_result.records_created,
            "records_updated": result.records_updated,
            "records_skipped": created_result.records_skipped + result.records_skipped,
        }
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import vhd-lead-enrichment CSV outputs into the master.")
    parser.add_argument("path", help="Enrichment CSV output.")
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    args = parser.parse_args(argv)
    print(import_enrichment_results(args.path, root_dir=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
