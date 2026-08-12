# Zillow County Choropleth

TECH 2335 Final Project — Residential Real Estate Data Visualizations

**Group:** Thomas Bowdon, Thomas Khadoo, Waqar Mahmood

## What it does

Zillow publishes a lot of housing data as CSV files, but their free charts make
it hard to compare many markets at once. This app pulls the newest Zillow data
and plots it on a **county-level choropleth map** so you can see how a value
changes across the country at a glance. Pick a metric from the dropdown and the
map redraws.

## How it's put together

| File | Role |
|------|------|
| `app.py` | The Streamlit web app (the interface + the map) |
| `zillow_data.py` | Fetches Zillow CSVs, builds the FIPS key, preps data for mapping |
| `requirements.txt` | Packages Render installs to run the app |
| `notebooks/` | The original exploration notebook, kept for reference |

The data flows in one direction: `zillow_data.py` downloads and cleans → `app.py`
asks it for a metric and draws the map. Keeping the data logic separate from the
app keeps both files short and easy to change.

## Where the data comes from

Home value and market data come from
[Zillow Research](https://www.zillow.com/research/data/). Files live at URLs like:

```
https://files.zillowstatic.com/research/public_csvs/{metric}/County_{metric}_{cut}.csv
```

Because the URL is built from tokens, we compose it in code instead of
downloading by hand. Monthly series update on the 16th of each month.

## "Routinely brings in the newest data"

The app caches each metric for 24 hours (`ttl=86400` in `app.py`). When the
cache expires, the next visitor triggers a fresh download — so the app always
shows recent data without needing a separate scheduled job. A scheduled monthly
refresh is listed under Future Work.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501).

## Deploy on Render

1. Push this repo to GitHub.
2. On [render.com](https://render.com), create a **New → Web Service** and
   connect this repo.
3. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
4. Create the service. First build takes a few minutes; after that you get a
   public URL.

## Metrics

The dropdown covers 18 of the 22 metrics in `zillow_metric_dictionary.md`, at
County geography (matches the choropleth's polygons). Four dictionary metrics
are left out because Zillow doesn't publish them at County level at all
(verified live against `files.zillowstatic.com`, not just the notebook's
catalog probe, since Zillow's available cuts drift over time):

- `sales_count_now` — Metro only
- `new_con_sales_count_raw` — Metro/State only
- `zhvf_growth` — Metro only
- `zorf_growth` — Metro only

Showing those would need a Metro- or State-level choropleth (different
geojson polygons), which is future work, not a metric-list change.

## Future work

- Scheduled monthly refresh (Render Cron Job) instead of cache expiry.
- A Metro/State choropleth to cover the 4 metrics with no County-level file.
- A time slider to animate a metric across months, not just the latest.
