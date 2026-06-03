from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
from pprint import pprint
from typing import Any

from .enrichment_results_adapter import import_enrichment_results
from .env_utils import parse_env_file
from .export_master_xlsx import export_master_xlsx
from .import_scrapes import import_scrape_files
from .normalizer import utc_now
from .verification_adapter import import_verification_results


ENV_KEYS = [
    "BRAVE_SEARCH_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_ID",
    "SERPER_API_KEY",
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
    "VHD_GOOGLE_SPREADSHEET_ID",
    "GOOGLE_APPLICATION_CREDENTIALS",
]

SECRET_KEYS = {
    "BRAVE_SEARCH_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "SERPER_API_KEY",
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
}

PROVIDER_ENV_KEYS = {
    "brave": "BRAVE_SEARCH_API_KEY",
    "serper": "SERPER_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "tavily": "TAVILY_API_KEY",
}

PROVIDER_LABELS = {
    "brave": "Brave Search fuer neue Scrape-Leads",
    "serper": "Serper fuer gezielte Search-Enrichment-Fallbacks",
    "firecrawl": "Firecrawl fuer Website-/Impressum-Fallbacks",
    "tavily": "Tavily fuer Research-Fallbacks",
    "google_sheets": "Google Sheets Sync fuer Clay Queue und Clay Results",
}


def main(argv: list[str] | None = None) -> int:
    result = run_setup_wizard(argv)
    pprint(result)
    return 0


def run_setup_wizard(argv: list[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    interactive = not args.yes
    root.mkdir(parents=True, exist_ok=True)

    allow_brave = _resolve_bool(args.allow_brave, interactive, PROVIDER_LABELS["brave"], True)
    allow_serper = _resolve_bool(args.allow_serper, interactive, PROVIDER_LABELS["serper"], False)
    allow_firecrawl = _resolve_bool(args.allow_firecrawl, interactive, PROVIDER_LABELS["firecrawl"], False)
    allow_tavily = _resolve_bool(args.allow_tavily, interactive, PROVIDER_LABELS["tavily"], False)
    allow_google_sheets = _resolve_bool(
        args.allow_google_sheets,
        interactive,
        PROVIDER_LABELS["google_sheets"],
        bool(args.spreadsheet_id and args.google_credentials),
    )

    env_path = root / ".env"
    env_values = parse_env_file(env_path)
    env_updates: dict[str, str] = {}
    _collect_provider_secret(env_updates, env_values, "brave", allow_brave, interactive)
    _collect_provider_secret(env_updates, env_values, "serper", allow_serper, interactive)
    _collect_provider_secret(env_updates, env_values, "firecrawl", allow_firecrawl, interactive)
    _collect_provider_secret(env_updates, env_values, "tavily", allow_tavily, interactive)

    if interactive:
        if allow_google_sheets and not args.spreadsheet_id:
            args.spreadsheet_id = _prompt_value(
                "Google Sheet ID fuer Clay Queue/Results",
                default=env_values.get("VHD_GOOGLE_SPREADSHEET_ID", ""),
            )
        if allow_google_sheets and not args.google_credentials:
            args.google_credentials = _prompt_value(
                "Pfad zur Google Service-Account JSON",
                default=env_values.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            )
    if args.spreadsheet_id:
        env_updates["VHD_GOOGLE_SPREADSHEET_ID"] = args.spreadsheet_id
    if args.google_credentials:
        env_updates["GOOGLE_APPLICATION_CREDENTIALS"] = args.google_credentials
    env_result = write_env_file(env_path, env_values, env_updates)

    crawler_policy_path = write_crawler_policy(root, allow_brave)
    enrichment_policy_path = write_enrichment_policy(
        root,
        allow_serper=allow_serper,
        allow_firecrawl=allow_firecrawl,
        allow_tavily=allow_tavily,
    )

    existing_leads_path = Path(args.existing_leads).expanduser() if args.existing_leads else None
    if interactive and not existing_leads_path and _prompt_yes_no(
        "Gibt es bereits eine Lead-Datei, die in den Master importiert werden soll?",
        default=False,
    ):
        existing_leads_path = Path(_prompt_value("Pfad zur bestehenden CSV/XLSX-Datei")).expanduser()
        args.existing_leads_kind = _prompt_choice(
            "Welche Art Datei ist das?",
            choices=["scrape", "verification", "enrichment"],
            default="scrape",
        )

    import_result: dict[str, Any] | None = None
    if existing_leads_path:
        resolved_existing = existing_leads_path.resolve()
        if args.existing_leads_kind == "verification":
            import_result = import_verification_results(resolved_existing, root_dir=root)
            export_master_xlsx(root_dir=root)
        elif args.existing_leads_kind == "enrichment":
            import_result = import_enrichment_results(resolved_existing, root_dir=root)
            export_master_xlsx(root_dir=root)
        else:
            import_result = import_scrape_files([resolved_existing], root_dir=root, write_xlsx=True)

    profile = {
        "created_at": utc_now(),
        "providers": {
            "brave": {"enabled": allow_brave},
            "serper": {"enabled": allow_serper},
            "firecrawl": {"enabled": allow_firecrawl},
            "tavily": {"enabled": allow_tavily},
            "google_sheets": {"enabled": allow_google_sheets},
        },
        "paths": {
            "env": str(env_path),
            "crawler_policy": str(crawler_policy_path),
            "enrichment_policy": str(enrichment_policy_path),
        },
        "existing_leads_import": {
            "path": str(existing_leads_path.resolve()) if existing_leads_path else "",
            "kind": args.existing_leads_kind if existing_leads_path else "",
            "result": import_result or {},
        },
    }
    profile_path = root / "config" / "install_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    run_script_path = write_run_script(
        root,
        allow_brave=allow_brave,
        allow_provider_enrichment=allow_serper or allow_firecrawl or allow_tavily,
        allow_google_sheets=allow_google_sheets,
    )
    profile["paths"]["install_profile"] = str(profile_path)
    profile["paths"]["run_script"] = str(run_script_path)
    profile["env"] = env_result
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return profile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive setup for the local VHD lead system installation."
    )
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    parser.add_argument("--yes", action="store_true", help="Use safe defaults and do not prompt.")
    _add_bool(parser, "brave", "Allow Brave Search scraping.")
    _add_bool(parser, "serper", "Allow Serper provider enrichment.")
    _add_bool(parser, "firecrawl", "Allow Firecrawl provider enrichment.")
    _add_bool(parser, "tavily", "Allow Tavily provider enrichment.")
    _add_bool(parser, "google-sheets", "Allow Google Sheets Clay sync.")
    parser.add_argument("--spreadsheet-id", help="Google Sheet id for Clay Queue and Clay Results.")
    parser.add_argument("--google-credentials", help="Path to Google service-account JSON.")
    parser.add_argument("--existing-leads", help="Existing CSV/XLSX lead file to import into master.")
    parser.add_argument(
        "--existing-leads-kind",
        choices=["scrape", "verification", "enrichment"],
        default="scrape",
        help="How to interpret --existing-leads.",
    )
    return parser


def _add_bool(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    dest = f"allow_{name.replace('-', '_')}"
    group = parser.add_mutually_exclusive_group()
    group.add_argument(f"--allow-{name}", dest=dest, action="store_true", help=help_text)
    group.add_argument(f"--no-{name}", dest=dest, action="store_false", help=f"Do not {help_text[0].lower()}{help_text[1:]}")
    parser.set_defaults(**{dest: None})


def _resolve_bool(value: bool | None, interactive: bool, label: str, default: bool) -> bool:
    if value is not None:
        return bool(value)
    if interactive:
        return _prompt_yes_no(f"{label} erlauben?", default=default)
    return default


def _collect_provider_secret(
    updates: dict[str, str],
    existing: dict[str, str],
    provider: str,
    enabled: bool,
    interactive: bool,
) -> None:
    key = PROVIDER_ENV_KEYS[provider]
    if not enabled:
        return
    if existing.get(key) and interactive:
        if _prompt_yes_no(f"{key} existiert bereits. Behalten?", default=True):
            return
    if interactive:
        value = getpass.getpass(f"{key} eintragen (leer lassen zum spaeteren Setzen): ").strip()
        if value:
            updates[key] = value
    elif key not in existing:
        updates[key] = ""


def _prompt_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{suffix}] ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "j", "ja"}


def _prompt_value(prompt: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _prompt_choice(prompt: str, *, choices: list[str], default: str) -> str:
    while True:
        answer = _prompt_value(f"{prompt} ({'/'.join(choices)})", default=default)
        if answer in choices:
            return answer
        print(f"Bitte einen dieser Werte verwenden: {', '.join(choices)}")


def write_env_file(path: Path, existing: dict[str, str], updates: dict[str, str]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# VHD Lead System local environment.",
        "# This file is intentionally ignored by git.",
        "",
        "# Search / scraping",
    ]
    for key in ["BRAVE_SEARCH_API_KEY", "GOOGLE_CSE_API_KEY", "GOOGLE_CSE_ID"]:
        lines.append(_format_env_line(key, merged.get(key, "")))
    lines.extend(["", "# Enrichment providers"])
    for key in ["SERPER_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY"]:
        lines.append(_format_env_line(key, merged.get(key, "")))
    lines.extend(["", "# Google Sheets"])
    for key in ["VHD_GOOGLE_SPREADSHEET_ID", "GOOGLE_APPLICATION_CREDENTIALS"]:
        lines.append(_format_env_line(key, merged.get(key, "")))

    extra_keys = sorted(key for key in merged if key not in ENV_KEYS)
    if extra_keys:
        lines.extend(["", "# Other existing values"])
        for key in extra_keys:
            lines.append(_format_env_line(key, merged.get(key, "")))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    missing_enabled = [key for key in updates if not updates[key] and key in SECRET_KEYS]
    return {"path": str(path), "written": True, "missing_secret_values": missing_enabled}


def _format_env_line(key: str, value: str) -> str:
    if not value:
        return f"{key}="
    if any(char.isspace() for char in value) or "#" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def write_crawler_policy(root: Path, allow_brave: bool) -> Path:
    path = root / "crawler_policy.json"
    example = root / "crawler_policy.example.json"
    policy = _read_json(example, default={})
    if path.exists():
        policy.update(_read_json(path, default={}))
    policy["brave_enabled"] = allow_brave
    if not allow_brave:
        policy["brave_daily_limit"] = 0
    path.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_enrichment_policy(
    root: Path,
    *,
    allow_serper: bool,
    allow_firecrawl: bool,
    allow_tavily: bool,
) -> Path:
    path = root / "config" / "enrichment_policy.json"
    example = root / "config" / "enrichment_policy.example.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    policy = _read_json(example, default={})
    if path.exists():
        policy.update(_read_json(path, default={}))
    providers = dict(policy.get("providers") or {})
    providers.setdefault("serper", {})["enabled"] = allow_serper
    providers.setdefault("firecrawl", {})["enabled"] = allow_firecrawl
    providers.setdefault("tavily", {})["enabled"] = allow_tavily
    providers.setdefault("clay", {})["enabled"] = False
    policy["providers"] = providers
    path.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_run_script(
    root: Path,
    *,
    allow_brave: bool,
    allow_provider_enrichment: bool,
    allow_google_sheets: bool,
) -> Path:
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / "run_vhd_lead_system.ps1"
    args = [
        '"--root"',
        '"$Root"',
        '"run-pipeline"',
        '"--provider"',
        '"brave"',
        '"--budget-calls"',
        '"5"',
        '"--query-limit"',
        '"5"',
        '"--verify-workers"',
        '"2"',
    ]
    if not allow_brave:
        args.append('"--skip-scrape"')
    if allow_provider_enrichment:
        args.append('"--run-provider-enrichment"')
    if allow_google_sheets:
        args.append('"--sync-google"')
    args.extend(['"--clay-batch-id"', '"obsidian_$Timestamp"'])
    script = f"""$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Python = if ($env:VHD_LEAD_PYTHON) {{ $env:VHD_LEAD_PYTHON }} else {{ "python" }}
Set-Location $Root

$RunArgs = @(
  {', '.join(args)}
)

& $Python -m vhd_lead_system.cli @RunArgs
"""
    path.write_text(script, encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
