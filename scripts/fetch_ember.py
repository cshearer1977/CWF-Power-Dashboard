"""
Fetch monthly Ember electricity-generation and power-sector-emissions data
for the target countries, write normalized JSON to scripts/_cache/ember.json.

Series we keep:
  - Coal            -> share_of_generation_pct, generation_twh
  - Wind and solar  -> share_of_generation_pct, generation_twh
  - Fossil (emissions endpoint) -> emissions_mtco2   (backup only;
        Climate TRACE is the primary CO2 source, but we keep this so we can
        fall back if CT is down)

Records which countries returned zero rows so Climate TRACE can fill those in.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from countries import TARGET_COUNTRIES

# ── Paths ──────────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
REPO = HERE.parent
CACHE_DIR = HERE / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
OUT_PATH = CACHE_DIR / "ember.json"

# ── API config ─────────────────────────────────────────────────────────────────
load_dotenv(REPO / ".env")
API_KEY = os.environ.get("EMBER_API_KEY")
if not API_KEY:
    sys.exit("ERROR: EMBER_API_KEY not set. Copy .env.example to .env or set the env var.")

GEN_URL = "https://api.ember-energy.org/v1/electricity-generation/monthly"
EMISSIONS_URL = "https://api.ember-energy.org/v1/power-sector-emissions/monthly"

START_DATE = "2025-01-01"
# end_date: always "today" so we pick up newly published months each cron run
from datetime import date
END_DATE = date.today().replace(day=1).isoformat()


def fetch(url: str, is_aggregate_series: bool) -> list[dict]:
    params = {
        "entity_code": ",".join(TARGET_COUNTRIES.keys()),
        "is_aggregate_series": str(is_aggregate_series).lower(),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "api_key": API_KEY,
    }
    r = requests.get(url, params=params, timeout=60)
    print(f"  [{r.status_code}] {url.split('/')[-1]} agg={is_aggregate_series}")
    r.raise_for_status()
    payload = r.json()
    if isinstance(payload, dict):
        return payload.get("data") or payload.get("results") or []
    return payload or []


def main() -> None:
    print(f"Ember fetch  {START_DATE} → {END_DATE}  ({len(TARGET_COUNTRIES)} countries)")

    # Non-aggregated gives us per-fuel series (we want "Coal")
    gen_non_agg = fetch(GEN_URL, is_aggregate_series=False)
    # Aggregated gives us "Wind and solar"
    gen_agg = fetch(GEN_URL, is_aggregate_series=True)
    # Aggregated emissions give us "Fossil"
    emis_agg = fetch(EMISSIONS_URL, is_aggregate_series=True)

    # Shape: { ISO3: { "YYYY-MM": {field: value, ...} } }
    out: dict[str, dict[str, dict]] = {iso3: {} for iso3 in TARGET_COUNTRIES}

    def row_bucket(iso3: str, date_str: str) -> dict:
        month = date_str[:7]  # YYYY-MM
        if month not in out[iso3]:
            out[iso3][month] = {}
        return out[iso3][month]

    # 1) Coal share + coal generation (TWh -> GWh)
    for r in gen_non_agg:
        if r.get("series") != "Coal":
            continue
        iso3 = r.get("entity_code")
        if iso3 not in out:
            continue
        b = row_bucket(iso3, r["date"])
        share = r.get("share_of_generation_pct")
        gen_twh = r.get("generation_twh")
        if share is not None:
            b["coal_share_pct"] = share
        if gen_twh is not None:
            b["coal_gwh"] = gen_twh * 1000.0

    # 2) Wind+solar share + generation
    for r in gen_agg:
        if r.get("series") != "Wind and solar":
            continue
        iso3 = r.get("entity_code")
        if iso3 not in out:
            continue
        b = row_bucket(iso3, r["date"])
        share = r.get("share_of_generation_pct")
        gen_twh = r.get("generation_twh")
        if share is not None:
            b["renewables_share_pct"] = share
        if gen_twh is not None:
            b["renewables_gwh"] = gen_twh * 1000.0

    # 3) Fossil power-sector emissions (kept as secondary CO2 source)
    for r in emis_agg:
        if r.get("series") != "Fossil":
            continue
        iso3 = r.get("entity_code")
        if iso3 not in out:
            continue
        b = row_bucket(iso3, r["date"])
        mt = r.get("emissions_mtco2")
        if mt is not None:
            b["co2_mt_ember"] = mt

    # Summary: which countries / fields are empty
    coverage: dict[str, dict[str, int]] = {}
    for iso3, months in out.items():
        fields = {"coal_share_pct": 0, "coal_gwh": 0,
                  "renewables_share_pct": 0, "renewables_gwh": 0,
                  "co2_mt_ember": 0}
        for m in months.values():
            for k in fields:
                if k in m and m[k] is not None:
                    fields[k] += 1
        coverage[iso3] = fields

    print("\nCoverage (non-null months per field):")
    headers = ["iso3", "coal%", "coalGWh", "re%", "reGWh", "co2(Mt)"]
    print("  " + "  ".join(f"{h:>8}" for h in headers))
    for iso3, fc in coverage.items():
        print(f"  {iso3:>8}  "
              f"{fc['coal_share_pct']:>8}  {fc['coal_gwh']:>8}  "
              f"{fc['renewables_share_pct']:>8}  {fc['renewables_gwh']:>8}  "
              f"{fc['co2_mt_ember']:>8}")

    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "data": out,
        "coverage": coverage,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
