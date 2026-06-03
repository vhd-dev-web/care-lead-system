from __future__ import annotations

from dataclasses import dataclass

from .clay import assess_clay_eligibility
from .normalizer import truthy
from .policy import EnrichmentPolicy
from .quality import is_enrichment_worthy, quality_rank


@dataclass(frozen=True)
class WaterfallDecision:
    next_step: str
    status: str
    reason: str
    provider: str = ""
    requires_external_provider: bool = False


def decide_next_step(row: dict[str, str], policy: EnrichmentPolicy | None = None) -> WaterfallDecision:
    active_policy = policy or EnrichmentPolicy()
    quality = row.get("lead_quality", "")
    if not is_enrichment_worthy(quality):
        return WaterfallDecision(
            next_step="store_only",
            status="queued_low_priority",
            reason="Lead quality is below A; no external enrichment or Clay.",
        )

    free_status = row.get("free_enrichment_status", "")
    if free_status not in {"complete", "website_enriched", "low_confidence", "failed"}:
        return WaterfallDecision(
            next_step="free_website_enrichment",
            status="queued_free_enrichment",
            reason="Run own website/imprint extraction before any provider.",
        )

    if not row.get("imprint_url"):
        return provider_decision(
            provider="serper",
            next_step="serper_find_imprint",
            reason="Imprint URL is missing after free enrichment.",
            policy=active_policy,
        )

    confidence = confidence_percent(row.get("confidence_score"), default=100)
    if row.get("imprint_parse_status") in {"failed", "low_confidence"} or confidence < 70:
        if truthy(row.get("firecrawl_used")):
            return WaterfallDecision(
                next_step="manual_review",
                status="queued_manual_review",
                reason="Firecrawl already ran; low-confidence result needs manual review.",
            )
        return provider_decision(
            provider="firecrawl",
            next_step="firecrawl_extract_known_url",
            reason="Known imprint/contact URL exists, but local extraction confidence is low.",
            policy=active_policy,
        )

    if not row.get("managing_director_name") and quality_rank(quality) >= quality_rank("A"):
        return provider_decision(
            provider="serper",
            next_step="serper_find_decision_maker",
            reason="Decision maker is missing after free enrichment.",
            policy=active_policy,
        )

    if truthy(row.get("entity_ambiguous")) or truthy(row.get("decision_maker_ambiguous")):
        if truthy(row.get("tavily_used")):
            return WaterfallDecision(
                next_step="manual_review",
                status="queued_manual_review",
                reason="Tavily research completed; ambiguous company or decision-maker evidence needs manual review.",
            )
        return provider_decision(
            provider="tavily",
            next_step="tavily_research_ambiguous_entity",
            reason="Company or decision maker is ambiguous and needs research summary.",
            policy=active_policy,
        )

    clay = assess_clay_eligibility(row)
    if clay.eligible:
        return provider_decision(
            provider="clay",
            next_step="clay_email_queue",
            reason=clay.reason,
            policy=active_policy,
        )

    return WaterfallDecision(
        next_step="compliance_review",
        status="queued_compliance_review",
        reason="Free enrichment is sufficient for review; Clay is not required.",
    )


def provider_decision(
    *,
    provider: str,
    next_step: str,
    reason: str,
    policy: EnrichmentPolicy,
) -> WaterfallDecision:
    if not policy.provider_enabled(provider):
        return WaterfallDecision(
            next_step=f"{next_step}_planned",
            status="provider_disabled",
            reason=f"{reason} Provider '{provider}' is disabled by policy.",
            provider=provider,
            requires_external_provider=True,
        )
    return WaterfallDecision(
        next_step=next_step,
        status="queued_provider_enrichment",
        reason=reason,
        provider=provider,
        requires_external_provider=True,
    )


def confidence_percent(value: object, default: int = 0) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        numeric = float(str(value).strip().replace(",", "."))
    except ValueError:
        return default
    if 0 <= numeric <= 1:
        numeric *= 100
    return int(round(numeric))
