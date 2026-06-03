from __future__ import annotations

import argparse
from pathlib import Path

from .export_master_xlsx import export_master_xlsx
from .io_utils import read_table
from .master_updater import MasterUpdater, source_name_for_path
from .run_registry import RunRegistry


def import_scrape_files(
    paths: list[str | Path],
    *,
    root_dir: str | Path = ".",
    write_xlsx: bool = True,
) -> dict[str, object]:
    registry = RunRegistry(root_dir)
    input_paths = [str(Path(path)) for path in paths]
    run = registry.start_run("scrape_import", input_paths=input_paths)
    updater = MasterUpdater(root_dir)
    totals = {"records_read": 0, "records_created": 0, "records_updated": 0, "records_skipped": 0}
    details: dict[str, object] = {"files": []}
    try:
        for path in paths:
            rows = read_table(path)
            result = updater.upsert_scrape_rows(rows, source_name=source_name_for_path(path), run_id=run.run_id)
            totals["records_read"] += result.records_read
            totals["records_created"] += result.records_created
            totals["records_updated"] += result.records_updated
            totals["records_skipped"] += result.records_skipped
            details["files"].append({"path": str(path), **result.__dict__})
        outputs = [str(updater.store.master_csv_path)]
        if write_xlsx:
            xlsx = export_master_xlsx(root_dir=root_dir, parent_run_id=run.run_id)
            outputs.append(str(xlsx))
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=outputs,
            records_read=totals["records_read"],
            records_written=totals["records_created"] + totals["records_updated"],
            records_created=totals["records_created"],
            records_updated=totals["records_updated"],
            records_skipped=totals["records_skipped"],
            detail=details,
        )
        return {"run_id": run.run_id, **totals, "outputs": outputs}
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc), detail=details)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import scrape CSV/XLSX files into the master.")
    parser.add_argument("paths", nargs="+", help="Scrape input files.")
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    parser.add_argument("--no-xlsx", action="store_true", help="Skip Leads_Master.xlsx generation.")
    args = parser.parse_args(argv)
    result = import_scrape_files(args.paths, root_dir=args.root, write_xlsx=not args.no_xlsx)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
