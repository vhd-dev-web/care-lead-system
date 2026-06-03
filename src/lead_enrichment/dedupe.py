from __future__ import annotations

from collections.abc import Iterable

from .normalizer import normalize_domain, parse_score, split_tokens, join_tokens


def dedupe_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    by_domain: dict[str, dict[str, str]] = {}
    for row in rows:
        domain = normalize_domain(row.get("domain") or row.get("source_url") or row.get("url"))
        if not domain:
            continue
        normalized = dict(row)
        normalized["domain"] = domain
        if domain not in by_domain:
            by_domain[domain] = normalized
            continue
        by_domain[domain] = merge_rows(by_domain[domain], normalized)
    return list(by_domain.values())


def merge_rows(existing: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    winner, loser = choose_better_row(existing, incoming), None
    loser = incoming if winner is existing else existing
    merged = dict(winner)
    for key, value in loser.items():
        if not merged.get(key) and value:
            merged[key] = value
    for key in ("signals", "input_signals", "possible_shop_levers", "verified_signals"):
        tokens = split_tokens(existing.get(key)) + split_tokens(incoming.get(key))
        if tokens:
            merged[key] = join_tokens(tokens)
    notes = [existing.get("notes", ""), incoming.get("notes", "")]
    merged["notes"] = " | ".join(note for note in notes if note)
    return merged


def choose_better_row(a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    score_a = max(
        parse_score(a.get("vhd_fit_score")),
        parse_score(a.get("lead_score")),
        parse_score(a.get("input_lead_score")),
    )
    score_b = max(
        parse_score(b.get("vhd_fit_score")),
        parse_score(b.get("lead_score")),
        parse_score(b.get("input_lead_score")),
    )
    if score_b > score_a:
        return b
    return a
