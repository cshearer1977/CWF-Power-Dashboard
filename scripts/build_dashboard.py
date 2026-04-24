"""
Merge Ember + Climate TRACE into a single JSON consumed by the dashboard.

Per-field source rules (resolved once per country-month, with per-field tags
so the dashboard can show provenance next to each chart):

  coal_share_pct     : Ember if present, else null
  coal_gwh           : Ember if present, else Climate TRACE
  renewables_share_pct : Ember only
  renewables_gwh     : Ember only
  co2_mt             : Climate TRACE primary, Ember ('Fossil') fallback

Output: docs/data/dashboard.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from countries import TARGET_COUNTRIES

HERE = Path(__file__).parent
REPO = HERE.parent
CACHE = HERE / "_cache"
OUT = REPO / "docs" / "data" / "dashboard.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def load(path: Path) -> dict:
    if not path.exists():
        print(f"WARN: {path} does not exist — treating as empty")
        return {"data": {}}
    return json.loads(path.read_text())


def main() -> None:
    ember = load(CACHE / "ember.json")
    ct = load(CACHE / "climate_trace.json")

    countries_out = {}
    for iso3, name in TARGET_COUNTRIES.items():
        emb = ember.get("data", {}).get(iso3, {})
        trc = ct.get("data", {}).get(iso3, {})
        months = sorted(set(emb.keys()) | set(trc.keys()))

        rows = []
        for m in months:
            e = emb.get(m, {})
            t = trc.get(m, {})

            # coal_share: Ember only
            coal_share = e.get("coal_share_pct")

            # coal_gwh: Ember preferred, CT fallback
            if e.get("coal_gwh") is not None:
                coal_gwh, coal_gwh_src = e["coal_gwh"], "ember"
            elif t.get("coal_gwh") is not None:
                coal_gwh, coal_gwh_src = t["coal_gwh"], "climate_trace"
            else:
                coal_gwh, coal_gwh_src = None, None

            # renewables (wind+solar): Ember only
            ren_share = e.get("renewables_share_pct")
            ren_gwh = e.get("renewables_gwh")

            # CO2: Climate TRACE primary, Ember fallback
            if t.get("co2_mt") is not None:
                co2, co2_src = t["co2_mt"], "climate_trace"
            elif e.get("co2_mt_ember") is not None:
                co2, co2_src = e["co2_mt_ember"], "ember"
            else:
                co2, co2_src = None, None

            rows.append({
                "month": m,
                "coal_share_pct": coal_share,
                "coal_gwh": coal_gwh,
                "coal_gwh_source": coal_gwh_src,
                "renewables_share_pct": ren_share,
                "renewables_gwh": ren_gwh,
                "co2_mt": co2,
                "co2_source": co2_src,
            })

        # Determine "which source is the country's coal source overall" for the note
        coal_sources = {r["coal_gwh_source"] for r in rows if r["coal_gwh_source"]}
        co2_sources = {r["co2_source"] for r in rows if r["co2_source"]}
        countries_out[iso3] = {
            "name": name,
            "rows": rows,
            "sources": {
                "coal": sorted(coal_sources),
                "renewables": ["ember"] if any(r["renewables_gwh"] is not None for r in rows) else [],
                "co2": sorted(co2_sources),
            },
        }

    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ember_fetched_at": ember.get("fetched_at"),
        "climate_trace_fetched_at": ct.get("fetched_at"),
        "countries": countries_out,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUT}  ({len(countries_out)} countries, "
          f"{sum(len(c['rows']) for c in countries_out.values())} monthly rows)")


if __name__ == "__main__":
    main()
