from __future__ import annotations

import argparse
from pathlib import Path

from .io_utils import read_table
from .master_updater import MasterUpdater, first_value
from .normalizer import bool_string, normalize_domain, parse_score, truthy, utc_now
from .run_registry import RunRegistry


VERIFICATION_ALIASES = {
    "lead_id": ("lead_id",),
    "domain_key": ("domain_key", "domain", "website_url", "url"),
    "website_url": ("website_url", "source_url", "url"),
    "verification_status": ("verification_status", "status"),
    "verification_score": ("verification_score", "vhd_fit_score", "score"),
    "domain_alive": ("domain_alive", "alive"),
    "is_shop": ("is_shop", "shop_detected"),
    "is_woocommerce": ("is_woocommerce", "woocommerce_detected"),
    "woocommerce_confidence": ("woocommerce_confidence",),
    "detected_platform": ("detected_platform",),
    "detected_platform_signals": ("detected_platform_signals",),
    "niche": ("niche",),
    "care_lead_type": ("care_lead_type",),
    "ik_number": ("ik_number",),
    "care_product_signals": ("care_product_signals",),
    "care_gkv_signals": ("care_gkv_signals",),
    "care_process_signals": ("care_process_signals",),
    "care_insurer_signals": ("care_insurer_signals",),
    "care_ratgeber_signals": ("care_ratgeber_signals",),
    "care_disqualifier_signals": ("care_disqualifier_signals",),
    "scale_indicators": ("scale_indicators",),
    "verification_evidence_url": ("verification_evidence_url", "evidence_url", "source_url", "url"),
    "verification_checked_at": ("verification_checked_at", "checked_at", "last_scored_at"),
    "verification_error": ("verification_error", "error", "error_reason", "policy_skip_reason"),
    "business_potential_score": ("business_potential_score", "vhd_fit_score", "score"),
    "lead_grade": ("lead_grade", "lead_quality", "overall_priority", "category"),
    "lead_grade_reason": ("lead_grade_reason", "possible_shop_levers", "notes", "error_reason"),
    "next_action": ("next_action",),
    "next_action_reason": ("next_action_reason", "waterfall_reason", "notes"),
    "review_reason": ("review_reason", "exclusion_reason", "policy_skip_reason", "error_reason"),
}


_SKIP_REASONS_TO_PRESERVE_PRIOR_VERIFICATION = {
    "domain_cooldown",
    "robots_blocked",
    "domain_blocked",
}


def build_verification_patch(row: dict[str, object]) -> dict[str, str]:
    # When the verifier skipped a domain because of a cooldown / robots
    # block, it writes a placeholder row with lead_type=skipped, is_shop=no,
    # vhd_fit_score=0. Treating that as a real verification result would
    # destroy the A++/A+ grades from the previous run. Touch only the
    # cooldown notice fields so the prior verification stays intact.
    lead_type = first_value(row, ("lead_type",)).lower()
    policy_skip = first_value(row, ("policy_skip_reason",)).lower()
    if lead_type == "skipped" and policy_skip in _SKIP_REASONS_TO_PRESERVE_PRIOR_VERIFICATION:
        domain_key = normalize_domain(first_value(row, ("domain_key", "domain", "website_url", "url")))
        if not domain_key:
            return {}
        return {
            "domain_key": domain_key,
            "domain": domain_key,
            "verification_error": policy_skip,
            "verification_checked_at": utc_now(),
        }

    patch = {field: first_value(row, aliases) for field, aliases in VERIFICATION_ALIASES.items()}
    patch["domain_key"] = normalize_domain(patch.get("domain_key"))
    patch["domain"] = patch["domain_key"]
    if not patch.get("lead_grade"):
        patch["lead_grade"] = grade_from_verification_row(row)
    if not patch.get("verification_status"):
        patch["verification_status"] = status_from_verification_row(row)
    if not patch.get("domain_alive"):
        patch["domain_alive"] = bool_string(domain_alive_from_row(row))
    if not patch.get("woocommerce_confidence") and patch.get("is_woocommerce"):
        patch["woocommerce_confidence"] = "0.85" if truthy(patch["is_woocommerce"]) else "0.10"
    if patch.get("lead_grade") in {"Review"} or first_value(row, ("lead_type",)) == "review":
        patch["manual_review_required"] = "true"
        patch["review_status"] = "manual_review"
    if patch.get("lead_grade") == "Reject":
        patch["review_status"] = "rejected"

    # do_not_contact reset: when a previous run (e.g. the WooCommerce
    # classification) flagged a domain do_not_contact=true and the
    # current run promotes it to a top-tier care lead, the stale flag
    # silently blocks the lead from the Clay queue. Resetting belongs
    # here because this adapter owns the verification truth.
    care_lead_type = first_value(row, ("care_lead_type",)).strip().lower()
    if (
        patch.get("lead_grade") in {"A++", "A+", "A"}
        and care_lead_type == "pflegebox_anbieter"
    ):
        # Only clear flags set by a previous automated pipeline run,
        # never overwrite a manual do_not_contact decision (signaled
        # by a non-pipeline-style do_not_contact_reason).
        patch["do_not_contact"] = "false"
        patch["do_not_contact_reason"] = ""

    if any(patch.get(field) for field in ("domain_alive", "is_shop", "is_woocommerce", "verification_score")):
        if not patch.get("verification_status"):
            patch["verification_status"] = "done"
    if patch.get("verification_status") and not patch.get("verification_checked_at"):
        patch["verification_checked_at"] = utc_now()
    return {key: value for key, value in patch.items() if value}


def status_from_verification_row(row: dict[str, object]) -> str:
    if first_value(row, ("error_reason", "verification_error", "error")):
        return "failed"
    if truthy(first_value(row, ("skipped_by_robots",))):
        return "blocked"
    if first_value(row, ("lead_type", "checked_at", "vhd_fit_score", "best_status", "score")):
        return "done"
    return ""


def domain_alive_from_row(row: dict[str, object]) -> bool:
    status = first_value(row, ("best_status", "http_status"))
    if status:
        return status.startswith(("2", "3"))
    reachable_pages = parse_score(first_value(row, ("reachable_pages",)))
    return reachable_pages > 0


def grade_from_verification_row(row: dict[str, object]) -> str:
    """Pick a lead grade based on the row's niche.

    The pflegebox niche (this fork's default) uses care-specific
    thresholds where the IK-Nummer is a bonus, not a requirement. Any
    other niche falls back to the original WooCommerce-shop logic so
    legacy data stays gradable.
    """
    category = first_value(row, ("category",))
    if category:
        return normalize_category(category)

    niche = first_value(row, ("niche",)).strip().lower()
    if niche == "pflegebox":
        return grade_from_care_row(row)

    return grade_from_shop_row(row)


def grade_from_care_row(row: dict[str, object]) -> str:
    """Care-niche grading driven by care_lead_type + vhd_fit_score.

    The IK-Nummer is treated as a bonus signal (already factored into
    the score by score_fit_care), not as a hard gate, because the
    Pflegehilfsmittel imprint rules do not require it to be published.
    Thresholds are calibrated to the score range we observed on the
    six reference providers (42–76 without/with IK on the imprint).
    """
    care_lead_type = first_value(row, ("care_lead_type", "lead_type")).lower()
    score = parse_score(first_value(row, ("vhd_fit_score", "score", "verification_score")))
    exclusion = first_value(row, ("exclusion_reason", "error_reason")).lower()

    if care_lead_type in {"rejected", "ratgeber_site", "service_provider"}:
        return "Reject"
    if exclusion in {"no_care_signals", "ratgeber_or_content_site", "out_of_icp_business_type"}:
        return "Reject"

    if care_lead_type == "pflegebox_anbieter":
        if score >= 75:
            return "A++"
        if score >= 60:
            return "A+"
        if score >= 45:
            return "A"
        if score >= 30:
            return "B"
        return "Review"

    if care_lead_type == "review":
        return "Review"

    # Unclassified care row: fall back to score-based bucketing so
    # downstream filters still have something to work with.
    if score >= 60:
        return "A"
    if score >= 45:
        return "B"
    if score >= 30:
        return "Review"
    return "C"


def grade_from_shop_row(row: dict[str, object]) -> str:
    """Original WooCommerce-shop grading; preserved for niche=woocommerce."""
    lead_type = first_value(row, ("lead_type",)).lower()
    detected_platform = first_value(row, ("detected_platform",)).lower()
    if detected_platform and detected_platform != "woocommerce":
        return "Reject"
    if first_value(row, ("exclusion_reason", "error_reason")) or lead_type in {
        "service_provider",
        "agency",
        "platform_provider",
        "publisher",
        "fulfillment_provider",
        "payment_provider",
        "non_target_platform",
    }:
        return "Reject"
    score = parse_score(first_value(row, ("vhd_fit_score", "score", "verification_score")))
    is_shop = truthy(first_value(row, ("is_shop",)))
    is_woocommerce = truthy(first_value(row, ("is_woocommerce", "woocommerce_detected")))
    has_lever = bool(first_value(row, ("possible_shop_levers",)))
    if is_woocommerce and score >= 85 and has_lever:
        return "A++"
    if is_woocommerce and score >= 70:
        return "A+"
    if is_shop and score >= 60:
        return "A"
    if is_shop and score >= 45:
        return "B"
    if lead_type == "review" or score >= 35:
        return "Review"
    return "C"


def normalize_category(category: str) -> str:
    normalized = category.strip().lower()
    mapping = {
        "a++": "A++",
        "a+": "A+",
        "a": "A",
        "b": "B",
        "c": "C",
        "review": "Review",
        "manual_review": "Review",
        "unknown": "Review",
        "excluded": "Reject",
        "reject": "Reject",
        "rejected": "Reject",
    }
    return mapping.get(normalized, category)


def import_verification_results(path: str | Path, *, root_dir: str | Path = ".") -> dict[str, object]:
    rows = read_table(path)
    patches = [build_verification_patch(row) for row in rows]
    registry = RunRegistry(root_dir)
    run = registry.start_run("verification_import", input_paths=[str(path)])
    updater = MasterUpdater(root_dir)
    try:
        created_result = updater.upsert_scrape_rows(rows, source_name=Path(path).stem, run_id=run.run_id)
        result = updater.update_leads(patches, run_id=run.run_id, step="verification", match_key="domain_key")
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
    parser = argparse.ArgumentParser(description="Import verification results into the master.")
    parser.add_argument("path", help="Verification CSV/XLSX.")
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    args = parser.parse_args(argv)
    print(import_verification_results(args.path, root_dir=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
