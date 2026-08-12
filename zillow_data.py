"""
zillow_data.py
--------------
All the data logic for the choropleth app, lifted out of the exploration
notebook so the Streamlit app can import it instead of copy-pasting cells.

Two things live here:
  1. A small menu of metrics the app can show (name -> the URL tokens).
  2. Functions to fetch a Zillow CSV, add the FIPS key, and hand back a
     tidy DataFrame ready to map.

Nothing here knows about Streamlit -- that keeps this file testable on its
own and makes the app.py file short.
"""

import io
import time

import numpy as np
import pandas as pd
import requests

BASE = "https://files.zillowstatic.com/research/public_csvs"

# ---------------------------------------------------------------------------
# The menu of metrics the app offers.
#
# Each entry is a friendly label -> the pieces needed to build the URL. We use
# County geography for everything because the choropleth draws county polygons.
# These "cut" strings were confirmed by HEAD-requesting the live Zillow CDN
# (files.zillowstatic.com) for County-level files, not just taken from the
# metric dictionary -- Zillow's catalog shifts over time so a cut that used
# to resolve isn't guaranteed to still exist.
#
# zillow_metric_dictionary.md lists 22 metrics total. Four of them are left
# out here because they have no County-level file at all (verified live):
#   - sales_count_now        -- Metro only
#   - new_con_sales_count_raw -- Metro/State only
#   - zhvf_growth            -- Metro only
#   - zorf_growth            -- Metro only
# They'd need a Metro or State choropleth (different geojson) to show, which
# is out of scope for this county map. See README "Future work".
# ---------------------------------------------------------------------------
METRICS = {
    "Typical Home Value (ZHVI)": {
        "metric": "zhvi",
        "cut": "uc_sfrcondo_tier_0.33_0.67_sm_sa_month",
        "kind": "dollars",
    },
    "Median Sale Price": {
        "metric": "median_sale_price",
        "cut": "uc_sfrcondo_sm_sa_month",
        "kind": "dollars",
    },
    "For-Sale Inventory": {
        "metric": "invt_fs",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
    },
    "New Listings": {
        "metric": "new_listings",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
    },
    "Newly Pending Listings": {
        "metric": "new_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
    },
    "Median List Price": {
        "metric": "mlp",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "dollars",
    },
    "Mean Sale-to-List Ratio": {
        "metric": "mean_sale_to_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
    },
    "Median Sale-to-List Ratio": {
        "metric": "median_sale_to_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
    },
    "Percent Sold Above List": {
        "metric": "pct_sold_above_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
    },
    "Percent Sold Below List": {
        "metric": "pct_sold_below_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
    },
    "Share of Listings With a Price Cut": {
        "metric": "perc_listings_price_cut",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
    },
    "Mean Days to Pending": {
        "metric": "mean_doz_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "days",
    },
    "Median Days to Pending": {
        "metric": "med_doz_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "days",
    },
    "Market Heat Index": {
        "metric": "market_temp_index",
        "cut": "uc_sfrcondo_month",
        "kind": "index",
    },
    "Zillow Observed Rent Index (ZORI)": {
        "metric": "zori",
        "cut": "uc_sfrcondomfr_sm_sa_month",
        "kind": "dollars",
    },
    "Affordable Home Price": {
        "metric": "affordable_price",
        "cut": "downpayment_0.20_uc_sfrcondo_tier_0.33_0.67_sm_sa_month",
        "kind": "dollars",
    },
    "New Homeowner Income Needed": {
        "metric": "new_homeowner_income_needed",
        "cut": "downpayment_0.20_uc_sfrcondo_tier_0.33_0.67_sm_sa_month",
        "kind": "dollars",
    },
    "New Renter Income Needed": {
        "metric": "new_renter_income_needed",
        "cut": "uc_sfrcondomfr_sm_sa_month",
        "kind": "dollars",
    },
}

# ---------------------------------------------------------------------------
# How each "kind" of value should be formatted on the map. Dollar metrics get
# a log color scale (see app.py) because a handful of metros run 10x the rest;
# everything else is linear. The format string is a Plotly/d3 number format
# used in both the hover tooltip and (for percent) the colorbar ticks.
# ---------------------------------------------------------------------------
KIND_FORMAT = {
    "dollars": "$,.0f",
    "percent": ".1%",
    "count": ",.0f",
    "days": ",.0f",
    "index": ",.0f",
}

DTYPES = {
    "StateCodeFIPS": "string",
    "MunicipalCodeFIPS": "string",
    "RegionName": "string",
}


def build_url(metric: str, cut: str, geography: str = "County") -> str:
    """Compose a Zillow CSV URL from its tokens (same pattern as the notebook)."""
    stem = f"{metric}_{cut}"
    cache_buster = int(time.time())
    return f"{BASE}/{metric}/{geography}_{stem}.csv?t={cache_buster}"


def fetch_csv(metric: str, cut: str, geography: str = "County") -> pd.DataFrame:
    """
    Download one Zillow CSV and return it as a DataFrame with a FIPS column.

    Raises requests.HTTPError if the URL doesn't resolve, so the app can
    show a friendly message instead of crashing.
    """
    url = build_url(metric, cut, geography)
    resp = requests.get(
        url, timeout=120, headers={"User-Agent": "PythonCourseProject/1.0"}
    )
    resp.raise_for_status()

    df = pd.read_csv(io.BytesIO(resp.content), dtype=DTYPES)
    return add_fips(df)


def add_fips(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the 5-digit county FIPS key the choropleth joins on.

    State code is padded to 2 digits, municipal code to 3, then concatenated:
    e.g. state '6' + county '37' -> '06037' (Los Angeles County).
    """
    df = df.copy()
    df["StateCodeFIPS"] = df["StateCodeFIPS"].apply(lambda x: str(x).zfill(2))
    df["MunicipalCodeFIPS"] = df["MunicipalCodeFIPS"].apply(lambda x: str(x).zfill(3))
    df["FIPS"] = df["StateCodeFIPS"] + df["MunicipalCodeFIPS"]
    return df


def latest_value_column(df: pd.DataFrame) -> str:
    """
    Find the newest month column. Date columns look like '2026-07-31', so we
    grab every column whose first 4 chars are digits and take the last one.
    Don't hardcode the date -- it changes every monthly release.
    """
    date_cols = [c for c in df.columns if c[:4].isdigit()]
    if not date_cols:
        raise ValueError("No date columns found in this CSV.")
    return date_cols[-1]


def prep_for_map(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """
    Reduce the wide CSV to just what the map needs: FIPS, names, and the most
    recent value (renamed to 'value'). Returns the tidy frame plus the name of
    the month column it used, so the app can put it in the title.
    """
    latest = latest_value_column(df)
    keep = ["FIPS", "RegionName", "State", "Metro", latest]
    tidy = (
        df[keep]
        .dropna(subset=[latest])
        .rename(columns={latest: "value"})
        .copy()
    )
    # Home values are heavily right-skewed, so a log column gives better color
    # spread on the map. Only meaningful for positive values.
    tidy["log_value"] = np.log10(tidy["value"].where(tidy["value"] > 0))
    return tidy, latest
