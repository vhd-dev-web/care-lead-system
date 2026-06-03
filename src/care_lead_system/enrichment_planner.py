from __future__ import annotations

import argparse
from pathlib import Path

from .master_store import MasterStore
from .master_updater import MasterUpdater
from .normalizer import bool_string, truthy
from .run_registry import RunRegistry


def plan_row(row: dict[str, str]) -> dict[str, str]:
    patch = {"lead_id": row.get("lead_id", "")}
    if truthy(row.get("do_not_contact")):
        patch.update(
            {
                "enrichment_stage": "blocked",
                "next_action": "none",
                "next_action_reason": "Lead is marked do-not-contact.",
                "firecrawl_needed": "false",
                "firecrawl_status": "blocked",
                "serper_needed": "false",
                "serper_status": "blocked",
                "tavily_needed": "false",
                "tavily_status": "blocked",
            }
        )
        return patch

    missing_company_data = not row.get("legal_name") or not row.get("imprint_url")
    missing_contact = not row.get("email_general") or not row.get("phone_main")
    missing_decision_maker = not row.get("decision_maker_1_name")
    high_priority = row.get("lead_grade") in {"A++", "A+", "A"}

    firecrawl_needed = missing_company_data or missing_contact
    serper_needed = high_priority and missing_decision_maker
    tavily_needed = high_priority and missing_decision_maker and row.get("lead_grade") in {"A++", "A+"}

    next_actions: list[str] = []
    if firecrawl_needed:
        next_actions.append("website_or_firecrawl_enrichment")
    if serper_needed:
        next_actions.append("serper_decision_maker_research")
    if tavily_needed:
        next_actions.append("tavily_manual_research_brief")
    if not next_actions:
        next_actions.append("review_gate")

    patch.update(
        {
            "enrichment_stage": "planned",
            "next_action": "|".join(next_actions),
            "next_action_reason": "Missing firm/contact/decision-maker fields after CSV import.",
            "firecrawl_needed": bool_string(firecrawl_needed),
            "firecrawl_status": "needed" if firecrawl_needed else "not_needed",
            "firecrawl_reason": "Missing website/imprint/contact fields." if firecrawl_needed else "Required fields already present.",
            "serper_needed": bool_string(serper_needed),
            "serper_status": "needed" if serper_needed else "not_needed",
            "serper_reason": "High-priority lead lacks decision maker." if serper_needed else "No automatic Serper step required.",
            "tavily_needed": bool_string(tavily_needed),
            "tavily_status": "needed" if tavily_needed else "not_needed",
            "tavily_reason": "A++/A+ decision-maker research needs manual-quality brief." if tavily_needed else "No automatic Tavily step required.",
        }
    )
    return patch


def plan_enrichment(root_dir: str | Path = ".") -> dict[str, object]:
    store = MasterStore(root_dir)
    rows = store.load_rows()
    patches = [plan_row(row) for row in rows]
    registry = RunRegistry(root_dir)
    run = registry.start_run("enrichment_plan")
    updater = MasterUpdater(root_dir)
    try:
        result = updater.update_leads(patches, run_id=run.run_id, step="enrichment_planner")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[str(store.master_csv_path)],
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
    parser = argparse.ArgumentParser(description="Plan enrichment module needs in the master.")
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    args = parser.parse_args(argv)
    print(plan_enrichment(root_dir=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
