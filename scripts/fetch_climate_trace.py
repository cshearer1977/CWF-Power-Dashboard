"""
Climate TRACE monthly fetch for the 15 target countries:

  1. Power-sector CO2 per country-month (primary CO2 source for the dashboard)
     GET /v7/sources/emissions?gadmId=ISO3&year=YYYY&gas=co2&sectors=power

  2. Coal generation per country-month — used to fill in countries the Ember
     monthly API does not cover. Plant-level aggregation:
     GET /v7/sources?sectors=power&gadmId=ISO3&year=YYYY  (filter assetType
        contains 'coal')  then  GET /v7/sources/:id  per plant for monthly
        activity (MWh) -> summed to country-month GWh.

Writes scripts/_cache/climate_trace.json with:
  {
    fetched_at: ...,
    years: [2025, 2026],
    data: {
       ISO3: {
         "YYYY-MM": { co2_mt: ..., coal_gwh: ..., coal_plant_count: ... }
       }
    }
  }

Climate TRACE does not require an API key.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

from countries import TARGET_COUNTRIES

HERE = Path(__file__).parent
CACHE_DIR = HERE / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
OUT_PATH = CACHE_DIR / "climate_trace.json"

BASE_URL = "https://api.climatetrace.org/v7"
GAS = "co2"
SECTOR = "power"
REQUEST_DELAY = 0.25  # polite pacing

# Fetch current year + prior year to keep things monthly and current.
YEARS = [date.today().year - 1, date.today().year]


# ── CO2 emissions (country-level timeseries) ──────────────────────────────────

def fetch_country_emissions_year(iso3: str, year: int) -> list[dict]:
    """Returns list of {year, month, gas, emissionsQuantity} or []."""
    try:
        r = requests.get(
            f"{BASE_URL}/sources/emissions",
            params={"gadmId": iso3, "year": year, "gas": GAS, "sectors": SECTOR},
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("totals", {}).get("timeseries", []) or []
    except Exception as e:
        print(f"  [ERROR] emissions {iso3} {year}: {e}", file=sys.stderr)
        return []


# ── Coal generation (plant-level, aggregated) ─────────────────────────────────

def get_power_sources(iso3: str, year: int) -> list[dict]:
    """Page through /v7/sources for all power sources in a country-year."""
    all_sources: list[dict] = []
    offset, limit = 0, 100
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/sources",
                params={
                    "sectors": SECTOR,
                    "gadmId": iso3,
                    "year": year,
                    "limit": limit,
                    "offset": offset,
                },
                timeout=30,
            )
            r.raise_for_status()
            page = r.json() or []
        except Exception as e:
            print(f"  [ERROR] sources {iso3} {year} offset={offset}: {e}", file=sys.stderr)
            break
        if not page:
            break
        all_sources.extend(page)
        if len(page) < limit:
            break
        offset += limit
        time.sleep(REQUEST_DELAY)
    return all_sources


def is_coal(source: dict) -> bool:
    return "coal" in (source.get("assetType") or "").lower()


def get_plant_monthly(plant_id: int, year: int) -> list[dict]:
    try:
        r = requests.get(
            f"{BASE_URL}/sources/{plant_id}",
            params={
                "start": str(year),
                "end": str(year),
                "timeGranularity": "month",
                "gas": GAS,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("emissions", []) or []
    except Exception as e:
        print(f"  [ERROR] source {plant_id} {year}: {e}", file=sys.stderr)
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Climate TRACE fetch  years={YEARS}  countries={len(TARGET_COUNTRIES)}")

    # data[iso3][YYYY-MM] = {co2_mt, coal_gwh, coal_plant_count}
    data: dict[str, dict[str, dict]] = {iso3: {} for iso3 in TARGET_COUNTRIES}
    # coal aggregation working dict
    coal_agg: dict[tuple, dict] = defaultdict(lambda: {"mwh": 0.0, "plants": 0})

    for iso3, name in TARGET_COUNTRIES.items():
        print(f"\n── {name} ({iso3}) ──")
        for year in YEARS:
            # 1) Country-level CO2
            ts = fetch_country_emissions_year(iso3, year)
            for row in ts:
                m = row.get("month")
                q = row.get("emissionsQuantity")
                if m is None or q is None:
                    continue
                key = f"{year}-{m:02d}"
                data[iso3].setdefault(key, {})
                data[iso3][key]["co2_mt"] = q / 1e6  # tonnes -> Mt
            time.sleep(REQUEST_DELAY)

            # 2) Coal plants in this country-year
            sources = get_power_sources(iso3, year)
            coal_plants = [s for s in sources if is_coal(s)]
            print(f"  [{year}] {len(sources)} sources, {len(coal_plants)} coal")
            for plant in coal_plants:
                pid = plant.get("id")
                if pid is None:
                    continue
                monthly = get_plant_monthly(pid, year)
                for m in monthly:
                    mon = m.get("month")
                    act = m.get("activity") or 0
                    if mon is None:
                        continue
                    coal_agg[(iso3, year, mon)]["mwh"] += act
                    coal_agg[(iso3, year, mon)]["plants"] += 1
                time.sleep(REQUEST_DELAY)

    # Fold coal aggregation into data dict
    for (iso3, year, month), d in coal_agg.items():
        key = f"{year}-{month:02d}"
        data[iso3].setdefault(key, {})
        data[iso3][key]["coal_gwh"] = d["mwh"] / 1e3  # MWh -> GWh
        data[iso3][key]["coal_plant_count"] = d["plants"]

    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "years": YEARS,
        "data": data,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
