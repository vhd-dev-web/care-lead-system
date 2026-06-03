from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .master_schema import EVIDENCE_VALUE_FIELDS, blank_master_row, ensure_master_columns
from .master_store import MasterStore
from .normalizer import (
    bool_string,
    clean_text,
    join_tokens,
    merge_token_values,
    normalize_domain,
    normalize_url,
    parse_confidence,
    stable_lead_id,
    utc_now,
)


@dataclass(frozen=True)
class UpdateResult:
    records_read: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0


SCRAPE_ALIASES = {
    "domain": ("domain", "domain_key", "website_domain", "shop_domain", "source_domain"),
    "url": ("url", "source_url", "page_url", "shop_url", "website", "website_url"),
    "website_url": ("website_url", "website", "homepage", "site_url", "shop_url", "url"),
    "shop_name": ("shop_name", "store_name", "shop", "title", "name"),
    "company_name": ("company_name", "company", "business_name", "legal_name", "name"),
    "country": ("country", "country_hint", "country_code"),
    "language": ("language", "lang", "locale"),
    "verification_status": ("verification_status",),
    "verification_score": ("verification_score", "domain_score"),
    "domain_alive": ("domain_alive", "alive"),
    "is_shop": ("is_shop", "shop_detected"),
    "is_woocommerce": ("is_woocommerce", "woocommerce_detected"),
    "woocommerce_confidence": ("woocommerce_confidence",),
    "shop_relevance_score": ("shop_relevance_score",),
    "technical_pain_score": ("technical_pain_score",),
    "conversion_pain_score": ("conversion_pain_score",),
    "business_potential_score": ("business_potential_score", "vhd_fit_score", "lead_score"),
    "lead_grade": ("lead_grade", "overall_priority", "lead_quality"),
    "lead_grade_reason": ("lead_grade_reason", "priority_reason"),
    "priority": ("priority", "overall_numeric_score"),
}


def first_value(row: dict[str, object], aliases: tuple[str, ...]) -> str:
    lower_map = {str(key).strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        value = lower_map.get(alias.lower())
        if clean_text(value):
            return clean_text(value)
    return ""


def source_name_for_path(path: str | Path) -> str:
    return Path(path).stem


class MasterUpdater:
    def __init__(self, root_dir: str | Path = ".") -> None:
        self.store = MasterStore(root_dir)

    def upsert_scrape_rows(
        self,
        input_rows: list[dict[str, object]],
        *,
        source_name: str,
        run_id: str,
        seen_at: str | None = None,
    ) -> UpdateResult:
        now = seen_at or utc_now()
        master_rows = self.store.load_rows()
        by_domain = {row["domain_key"]: row for row in master_rows if row.get("domain_key")}
        created = 0
        updated = 0
        skipped = 0

        for input_row in input_rows:
            normalized = self._normalize_scrape_row(input_row)
            domain_key = normalized.get("domain_key", "")
            if not domain_key:
                skipped += 1
                continue
            existing = by_domain.get(domain_key)
            if existing is None:
                lead_id = stable_lead_id(domain_key)
                new_row = blank_master_row()
                new_row.update(normalized)
                new_row["lead_id"] = lead_id
                new_row["domain_key"] = domain_key
                new_row["domain"] = domain_key
                new_row["website_url"] = normalized.get("website_url") or normalize_url("", domain_key)
                new_row["source_lists"] = source_name
                new_row["scrape_source_primary"] = source_name
                new_row["scrape_sources_all"] = source_name
                new_row["scrape_run_ids"] = run_id
                new_row["first_seen_at"] = now
                new_row["last_seen_at"] = now
                new_row["created_at"] = now
                new_row["updated_at"] = now
                new_row["duplicate_group_id"] = domain_key
                new_row["duplicate_status"] = "canonical"
                new_row["canonical_lead_id"] = lead_id
                new_row["last_run_id"] = run_id
                master_rows.append(ensure_master_columns(new_row))
                by_domain[domain_key] = master_rows[-1]
                created += 1
                continue

            changed = self._merge_scrape_into_existing(existing, normalized, source_name, run_id, now)
            if changed:
                updated += 1

        self.store.write_rows(master_rows)
        return UpdateResult(
            records_read=len(input_rows),
            records_created=created,
            records_updated=updated,
            records_skipped=skipped,
        )

    def update_leads(
        self,
        patches: list[dict[str, object]],
        *,
        run_id: str,
        step: str,
        match_key: str = "lead_id",
    ) -> UpdateResult:
        now = utc_now()
        master_rows = self.store.load_rows()
        index = self._build_index(master_rows, match_key)
        updated = 0
        skipped = 0
        for patch in patches:
            key_value = self._patch_key_value(patch, match_key)
            row = index.get(key_value)
            if row is None:
                skipped += 1
                continue
            if self._apply_patch(row, patch, run_id=run_id, step=step, now=now):
                updated += 1
        self.store.write_rows(master_rows)
        return UpdateResult(records_read=len(patches), records_updated=updated, records_skipped=skipped)

    def _normalize_scrape_row(self, row: dict[str, object]) -> dict[str, str]:
        values = {field: first_value(row, aliases) for field, aliases in SCRAPE_ALIASES.items()}
        domain_key = normalize_domain(values.get("domain") or values.get("website_url") or values.get("url"))
        values["domain_key"] = domain_key
        values["domain"] = domain_key
        values["url"] = normalize_url(values.get("url"), domain_key)
        values["website_url"] = normalize_url(values.get("website_url") or values.get("url"), domain_key)
        return {key: value for key, value in values.items() if value}

    def _merge_scrape_into_existing(
        self,
        existing: dict[str, str],
        incoming: dict[str, str],
        source_name: str,
        run_id: str,
        now: str,
    ) -> bool:
        before = dict(existing)
        for field in (
            "url",
            "website_url",
            "shop_name",
            "company_name",
            "country",
            "language",
            "verification_status",
            "verification_score",
            "domain_alive",
            "is_shop",
            "is_woocommerce",
            "woocommerce_confidence",
            "shop_relevance_score",
            "technical_pain_score",
            "conversion_pain_score",
            "business_potential_score",
            "lead_grade",
            "lead_grade_reason",
            "priority",
        ):
            value = incoming.get(field, "")
            if value and not existing.get(field):
                existing[field] = value
        existing["source_lists"] = merge_token_values(existing.get("source_lists"), source_name)
        existing["scrape_sources_all"] = merge_token_values(existing.get("scrape_sources_all"), source_name)
        existing["scrape_run_ids"] = merge_token_values(existing.get("scrape_run_ids"), run_id)
        existing["last_seen_at"] = now
        existing["updated_at"] = now
        existing["last_run_id"] = run_id
        if not existing.get("canonical_lead_id"):
            existing["canonical_lead_id"] = existing.get("lead_id", "")
        if not existing.get("duplicate_group_id"):
            existing["duplicate_group_id"] = existing.get("domain_key", "")
        if not existing.get("duplicate_status"):
            existing["duplicate_status"] = "canonical"
        return before != existing

    def _build_index(self, rows: list[dict[str, str]], match_key: str) -> dict[str, dict[str, str]]:
        if match_key == "domain_key":
            return {row.get("domain_key", ""): row for row in rows if row.get("domain_key")}
        if match_key == "domain":
            return {normalize_domain(row.get("domain")): row for row in rows if normalize_domain(row.get("domain"))}
        return {row.get(match_key, ""): row for row in rows if row.get(match_key)}

    def _patch_key_value(self, patch: dict[str, object], match_key: str) -> str:
        value = clean_text(patch.get(match_key, ""))
        if value:
            return normalize_domain(value) if match_key in {"domain", "domain_key"} else value
        domain = clean_text(patch.get("domain_key") or patch.get("domain") or patch.get("website_url") or patch.get("url"))
        return normalize_domain(domain) if match_key in {"domain", "domain_key"} else value

    def _apply_patch(
        self,
        row: dict[str, str],
        patch: dict[str, object],
        *,
        run_id: str,
        step: str,
        now: str,
    ) -> bool:
        before = dict(row)
        patch_text = {str(key): clean_text(value) for key, value in patch.items() if clean_text(value)}
        for field in EVIDENCE_VALUE_FIELDS:
            self._apply_evidence_patch(row, patch_text, field)
        for key, value in patch_text.items():
            if key in {"lead_id", "domain_key", "domain"} or key in self._evidence_related_keys():
                continue
            row[key] = value
        row["updated_at"] = now
        row["last_run_id"] = run_id
        if step:
            row["last_completed_step"] = step
            row["last_completed_at"] = now
        return before != row

    def _apply_evidence_patch(self, row: dict[str, str], patch: dict[str, str], field: str) -> None:
        value = patch.get(field)
        if not value:
            return
        existing_confidence = parse_confidence(row.get(f"{field}_confidence"))
        incoming_confidence = parse_confidence(patch.get(f"{field}_confidence"))
        if row.get(field) and incoming_confidence and existing_confidence > incoming_confidence:
            return
        if row.get(field) and not incoming_confidence and existing_confidence:
            return
        row[field] = value
        for suffix in ("source", "confidence", "checked_at"):
            key = f"{field}_{suffix}"
            if patch.get(key):
                row[key] = patch[key]

    def _evidence_related_keys(self) -> set[str]:
        keys: set[str] = set(EVIDENCE_VALUE_FIELDS)
        for field in EVIDENCE_VALUE_FIELDS:
            keys.update({f"{field}_source", f"{field}_confidence", f"{field}_checked_at"})
        return keys
