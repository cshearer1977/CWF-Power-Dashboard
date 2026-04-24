# Monthly Power Sector Dashboard — 15 Countries

A static dashboard that tracks three monthly indicators for 15 countries
(South Africa, Kenya, Mexico, Brazil, Indonesia, Vietnam, Nigeria, Ethiopia,
Tanzania, Senegal, Ghana, Philippines, Pakistan, Thailand, Colombia):

1. **Coal generation** — share of total electricity generation (%) and absolute (GWh)
2. **Wind + solar generation** — share of total electricity generation (%) and absolute (GWh)
3. **Power-sector CO₂ emissions** — country-level monthly (Mt CO₂)

Data comes from Ember (primary for coal + wind/solar) and Climate TRACE
(primary for CO₂, and a fallback for coal generation in countries Ember's
monthly API does not cover).

## Layout

```
dashboard/
├── .env.example                    # copy to .env; holds EMBER_API_KEY
├── .gitignore                      # keeps .env and cache CSVs out of git
├── requirements.txt
├── scripts/
│   ├── countries.py                # shared 15-country list
│   ├── fetch_ember.py              # writes scripts/_cache/ember.json
│   ├── fetch_climate_trace.py      # writes scripts/_cache/climate_trace.json
│   └── build_dashboard.py          # merges both -> docs/data/dashboard.json
├── docs/                           # this folder is what GitHub Pages serves
│   ├── index.html                  # country selector + 3 Chart.js charts
│   └── data/
│       └── dashboard.json          # regenerated daily
└── .github/workflows/update-data.yml   # cron 06:15 UTC + manual dispatch
```

## Local run

```bash
cp .env.example .env          # then edit .env to set EMBER_API_KEY
pip install -r requirements.txt
python scripts/fetch_ember.py
python scripts/fetch_climate_trace.py
python scripts/build_dashboard.py
# Open docs/index.html via a local static server:
python -m http.server --directory docs 8000
# then visit http://localhost:8000
```

Opening `docs/index.html` directly with `file://` will work in some browsers
but Chrome blocks the `fetch('data/dashboard.json')` call over `file://`.
Use the `http.server` command above.

## GitHub setup

1. Push this folder to a new GitHub repo.
2. In **Settings → Secrets and variables → Actions**, add a repository secret
   named `EMBER_API_KEY` with your Ember key.
3. In **Settings → Pages**, set "Source" to **GitHub Actions**.
4. Trigger the first run: **Actions → Daily data refresh → Run workflow**.
   Subsequent runs are automatic at 06:15 UTC daily.

The workflow commits the refreshed `docs/data/dashboard.json` back to `main`
and deploys `docs/` to Pages in the same run.

## Data-source choices

| Field | Primary | Fallback |
|---|---|---|
| Coal share of generation (%) | Ember | — |
| Coal generation (GWh) | Ember | Climate TRACE (plant-level aggregation) |
| Wind + solar share (%) | Ember | — |
| Wind + solar generation (GWh) | Ember | — |
| Power-sector CO₂ (Mt) | Climate TRACE | Ember (`Fossil` series) |

The dashboard shows the active source per chart, per country, in the card
header (e.g. "Coal GWh: Ember + Climate TRACE") so readers can see which
methodology applies.

## Extending

- Add a country: edit `scripts/countries.py` and push. Next cron run will
  include it.
- Change time window: `scripts/fetch_ember.py`'s `START_DATE` constant and
  `scripts/fetch_climate_trace.py`'s `YEARS` list.
- Add a metric: extend `fetch_*.py` to capture it, then add a field and a
  chart in `build_dashboard.py` / `docs/index.html`.
