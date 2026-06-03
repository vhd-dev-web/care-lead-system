from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from .io_utils import read_table
from .master_store import MasterStore
from .master_updater import MasterUpdater, first_value
from .normalizer import clean_text, normalize_domain, truthy, utc_now
from .run_registry import RunRegistry


CLAY_QUEUE_COLUMNS = [
    "lead_id",
    "domain",
    "website_url",
    "company_name",
    "country",
    "language",
    "lead_grade",
    "clay_reason",
    "shop_relevance_score",
    "technical_pain_score",
    "business_potential_score",
    "imprint_url",
    "legal_name",
    "email_general",
    "phone_main",
    "decision_maker_1_name",
    "decision_maker_1_role",
    "linkedin_company_url",
    "recommended_outreach_channel",
    "outreach_angle",
    "clay_export_batch_id",
]

CLAY_RESULT_ALIASES = {
    "lead_id": ("lead_id",),
    "domain_key": ("domain_key", "domain", "website_url", "url"),
    "legal_name": ("legal_name", "company_legal_name"),
    "imprint_url": ("imprint_url",),
    "email_general": ("email_general", "email_business", "business_email", "email"),
    "phone_main": ("phone_main", "phone_business", "business_phone", "phone"),
    "decision_maker_1_name": ("decision_maker_1_name", "decision_maker_name", "person_name"),
    "decision_maker_1_role": ("decision_maker_1_role", "decision_maker_role", "person_role"),
    "linkedin_company_url": ("linkedin_company_url", "company_linkedin_url"),
    "linkedin_person_url": ("linkedin_person_url", "person_linkedin_url"),
    "clay_status": ("clay_status", "status"),
    "clay_notes": ("clay_notes", "notes"),
}

CLAY_ACTIVE_STATUSES = {"queued", "running", "done", "partial"}


@dataclass(frozen=True)
class ClayDecision:
    needed: bool
    reason: str


@dataclass(frozen=True)
class ClayQueuePlan:
    queue_rows: list[dict[str, str]]
    patches: list[dict[str, str]]


def has_business_contact(row: dict[str, str]) -> bool:
    return bool(row.get("email_general") or row.get("phone_main"))


def assess_clay_need(row: dict[str, str]) -> ClayDecision:
    grade = clean_text(row.get("lead_grade"))
    if truthy(row.get("do_not_contact")):
        return ClayDecision(False, "Lead is marked do-not-contact.")
    if grade == "Reject":
        return ClayDecision(False, "Rejected leads never go to Clay.")
    if grade == "Review":
        return ClayDecision(False, "Review leads require manual decision before Clay.")
    if grade in {"B", "C"}:
        return ClayDecision(False, "B/C leads are not automatically sent to Clay.")
    if grade == "A++":
        return ClayDecision(True, "A++ lead always goes to Clay in phase 1.")
    if grade == "A+":
        if not row.get("decision_maker_1_name"):
            return ClayDecision(True, "A+ lead is missing a decision maker.")
        if not has_business_contact(row):
            return ClayDecision(True, "A+ lead has no business contact path.")
        return ClayDecision(False, "A+ lead already has decision maker and business contact path.")
    if grade == "A":
        return ClayDecision(True, "A lead goes to Clay during the start phase.")
    return ClayDecision(False, "Lead grade is not eligible for automatic Clay handoff.")


def recommended_channel(row: dict[str, str]) -> str:
    if row.get("recommended_outreach_channel"):
        return row["recommended_outreach_channel"]
    if row.get("phone_main"):
        return "phone"
    if row.get("email_general"):
        return "email_review"
    if row.get("linkedin_company_url"):
        return "manual_linkedin_company_review"
    return "clay_enrich_first"


def outreach_angle(row: dict[str, str]) -> str:
    if row.get("outreach_angle"):
        return row["outreach_angle"]
    if row.get("lead_grade") in {"A++", "A+"}:
        return "Prioritize a concrete WooCommerce growth lever before outreach."
    return "Review shop fit and define the most concrete WooCommerce lever."


def build_clay_queue_plan(
    rows: list[dict[str, str]],
    *,
    batch: str,
    include_already_exported: bool = False,
) -> ClayQueuePlan:
    patches: list[dict[str, str]] = []
    queue_rows: list[dict[str, str]] = []
    for row in rows:
        decision = assess_clay_need(row)
        already_active = row.get("clay_status") in CLAY_ACTIVE_STATUSES
        if not decision.needed:
            if row.get("clay_status", "") in {"", "not_needed"}:
                patches.append(
                    {
                        "lead_id": row.get("lead_id", ""),
                        "clay_needed": "false",
                        "clay_reason": decision.reason,
                        "clay_status": "not_needed",
                    }
                )
            continue
        if already_active and not include_already_exported:
            continue
        queue_rows.append(build_queue_row(row, decision.reason, batch))
        patches.append(
            {
                "lead_id": row.get("lead_id", ""),
                "clay_needed": "true",
                "clay_reason": decision.reason,
                "clay_status": "queued",
                "clay_export_batch_id": batch,
                "clay_exported_at": utc_now(),
            }
        )
    return ClayQueuePlan(queue_rows=queue_rows, patches=patches)


def export_clay_queue(
    *,
    root_dir: str | Path = ".",
    output_path: str | Path | None = None,
    batch_id: str | None = None,
    include_already_exported: bool = False,
) -> dict[str, object]:
    store = MasterStore(root_dir)
    rows = store.load_rows()
    batch = batch_id or f"clay_{utc_now().replace('-', '').replace(':', '').replace('Z', '')}"
    target = Path(output_path) if output_path else Path(root_dir) / "output" / "lead_to_clay" / f"{batch}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    registry = RunRegistry(root_dir)
    run = registry.start_run("lead_to_clay_export", input_paths=[str(store.master_csv_path)])
    try:
        plan = build_clay_queue_plan(rows, batch=batch, include_already_exported=include_already_exported)

        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CLAY_QUEUE_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(plan.queue_rows)

        updater = MasterUpdater(root_dir)
        result = updater.update_leads(plan.patches, run_id=run.run_id, step="lead_to_clay_export")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[str(target), str(store.master_csv_path)],
            records_read=len(rows),
            records_written=len(plan.queue_rows),
            records_updated=result.records_updated,
            records_skipped=result.records_skipped,
            detail={"batch_id": batch, "queue_rows": len(plan.queue_rows)},
        )
        return {"run_id": run.run_id, "batch_id": batch, "queue_path": str(target), "records_written": len(plan.queue_rows)}
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc))
        raise


def build_queue_row(row: dict[str, str], reason: str, batch: str) -> dict[str, str]:
    values = {column: row.get(column, "") for column in CLAY_QUEUE_COLUMNS}
    values["domain"] = row.get("domain") or row.get("domain_key", "")
    values["company_name"] = row.get("company_name") or row.get("shop_name") or row.get("legal_name", "")
    values["clay_reason"] = reason
    values["recommended_outreach_channel"] = recommended_channel(row)
    values["outreach_angle"] = outreach_angle(row)
    values["clay_export_batch_id"] = batch
    return values


def build_clay_result_patch(row: dict[str, object]) -> dict[str, str]:
    patch = {field: first_value(row, aliases) for field, aliases in CLAY_RESULT_ALIASES.items()}
    patch["domain_key"] = normalize_domain(patch.get("domain_key"))
    now = utc_now()
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
            patch.setdefault(f"{field}_source", "clay")
            patch.setdefault(f"{field}_confidence", "0.70")
            patch.setdefault(f"{field}_checked_at", now)
    if patch.get("decision_maker_1_role"):
        patch.setdefault("decision_maker_1_source", "clay")
        patch.setdefault("decision_maker_1_confidence", "0.70")
        patch.setdefault("decision_maker_1_checked_at", now)
    patch["clay_status"] = patch.get("clay_status") or "done"
    patch["clay_last_synced_at"] = now
    patch["clay_result_imported_at"] = now
    return {key: value for key, value in patch.items() if value}


def import_clay_results(path: str | Path, *, root_dir: str | Path = ".") -> dict[str, object]:
    rows = read_table(path)
    patches = [build_clay_result_patch(row) for row in rows]
    registry = RunRegistry(root_dir)
    run = registry.start_run("lead_to_clay_import", input_paths=[str(path)])
    updater = MasterUpdater(root_dir)
    try:
        result = updater.update_leads(patches, run_id=run.run_id, step="lead_to_clay_import")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[str(updater.store.master_csv_path)],
            records_read=result.records_read,
            records_written=result.records_updated,
            records_updated=result.records_updated,
            records_skipped=result.records_skipped,
        )
        return {"run_id": run.run_id, **result.__dict__}
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export/import Clay CSV handoff files.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--root", default=".")
    export_parser.add_argument("--output")
    export_parser.add_argument("--batch-id")
    export_parser.add_argument("--include-already-exported", action="store_true")
    import_parser = subparsers.add_parser("import-results")
    import_parser.add_argument("path")
    import_parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    if args.command == "export":
        print(
            export_clay_queue(
                root_dir=args.root,
                output_path=args.output,
                batch_id=args.batch_id,
                include_already_exported=args.include_already_exported,
            )
        )
    else:
        print(import_clay_results(args.path, root_dir=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
