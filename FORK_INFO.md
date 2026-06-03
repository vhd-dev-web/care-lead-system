# Fork Information

This project is a fork of `vhd-lead-system`, created to target a different
Ideal Customer Profile (ICP): German **Pflegehilfsmittel** providers
(care aid suppliers) instead of WooCommerce shops.

## Origin

- **Source repo**: https://github.com/vhd-dev-web/vhd-lead-system
- **Forked from commit**: `6574c185cabdf3a909cba7a96eda3094faf7ac3b`
- **Source branch**: `codex/vhd-lead-system-phase-2`
- **Fork date**: 2026-06-03

## Why a hard fork (not a shared package with ICP profiles)

The two ICPs diverge in non-trivial ways:

- Search queries (WooCommerce signal vs. Pflegebox / GKV signal)
- Verifier markers (`add-to-cart`, `wp-content/plugins/woocommerce`
  vs. IK-Nummer, §40/42/78 SGB XI, "Pflegekasse", "Pflegegrad")
- Lead grading (shop fit vs. GKV-Vertragspartner-Skala)
- Negative filters (other shop platforms vs. content/ratgeber sites)

Sharing one codebase via an `--icp` flag would have meant either a large
refactor up front or a leaky abstraction. The fork keeps both systems
evolvable independently. Bug fixes that apply to both can be cherry-picked
across.

## What is in scope to change

- `src/vhd_lead_system/scraper/woocommerce_lead_finder.py` → care variant
- `src/vhd_lead_system/scraper/lead_qualifier.py` markers
- `src/vhd_lead_system/master_schema.py` adds Pflege-specific fields
  (`ik_number`, `gkv_signals`, `scale_indicators`)
- User-Agent in `crawler_policy.json` must look like a real browser —
  many Pflegehilfsmittel providers return HTTP 403 to bot user-agents
- Brave query bank and negative terms
- Lead grading thresholds

## What stays as is (and should be kept compatible with the origin)

- Master CSV schema base columns
- Pipeline orchestration (`pipeline_runner.py`)
- Google Sheets adapter, master updater, run registry
- Test infrastructure (`tests/conftest.py` hermetic env scrubbing)
- Cooldown-skip preservation logic in `verification_adapter.py`

## Reference HTML samples used to derive Pflegehilfsmittel markers

All six providers below run WooCommerce, all have a 9-digit IK-Nummer
in their Impressum, and all share the same vocabulary (Pflegebox,
Pflegegrad, §40/42 SGB XI, "Pflegekasse übernimmt", "Vertragspartner"):

- https://pflegemittelbox.de/  — IK 324852098
- https://sanubi.de/           — IK 176364028
- https://pflegebox.de/        — IK 176364027
- https://www.mein-pflegeset.de/ — IK 080000083
- https://box4pflege.de/       — IK 214748364
- https://www.hygibox.de/      — IK 330556898
