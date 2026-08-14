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

# Census Bureau Vintage 2025 Population & Housing Unit Estimates, used to
# normalize "count" metrics (inventory, listings) to a per-1,000-housing-units
# basis so counties aren't just ranked by population size. Both come from the
# same Census release, so the county names in the housing-unit workbook line
# up exactly with the names in the population crosswalk.
#
# The housing-unit file only ships as an XLSX press table (Geographic Area:
# ".Autauga County, Alabama") with no FIPS column, and the Census Data API
# (api.census.gov) now requires a signed-up key for every query -- including
# this one -- so instead we join the workbook's county names against
# co-est2025-alldata.csv, an unrestricted CSV of the same vintage that does
# carry STATE/COUNTY FIPS codes alongside matching STNAME/CTYNAME columns.
CENSUS_HOUSING_UNITS_URL = (
    "https://www2.census.gov/programs-surveys/popest/tables/2020-2025/"
    "housing/totals/CO-EST2025-HU.xlsx"
)
CENSUS_FIPS_CROSSWALK_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/"
    "counties/totals/co-est2025-alldata.csv"
)

# ---------------------------------------------------------------------------
# The menu of metrics the app offers.
#
# Each entry is a friendly label -> the pieces needed to build the URL, plus a
# "category" used to group the dropdown in app.py. Categories mirror the
# Category column in zillow_metric_dictionary.md so the two stay consistent.
# We use County geography for everything because the choropleth draws county
# polygons. These "cut" strings were confirmed by HEAD-requesting the live
# Zillow CDN (files.zillowstatic.com) for County-level files, not just taken
# from the metric dictionary -- Zillow's catalog shifts over time so a cut
# that used to resolve isn't guaranteed to still exist.
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
        "category": "Home Values",
        # Price-level metrics have no universal "good" direction (a buyer
        # wants low, a seller/owner wants high) -- higher_is_better just
        # ranks magnitude here, it isn't a value judgment. See the other
        # False entries below for metrics where a direction IS well-defined
        # by real-estate convention (days on market, price cuts, etc.).
        "higher_is_better": True,
        "description": (
            "Typical home value and market change for a region and housing "
            "type, reflecting the 35th-65th percentile of values. Represents "
            "the whole housing stock, not just homes that sold -- it is not "
            "a median sale price."
        ),
    },
    "Median Sale Price": {
        "metric": "median_sale_price",
        "cut": "uc_sfrcondo_sm_sa_month",
        "kind": "dollars",
        "category": "Sales",
        "higher_is_better": True,  # price level, magnitude only -- see ZHVI note above
        "description": (
            "Median price at which homes sold. Latest month is nowcast to "
            "account for sales-reporting latency."
        ),
    },
    "Mean Sale-to-List Ratio": {
        "metric": "mean_sale_to_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
        "category": "Sales",
        "higher_is_better": True,  # closer to/above list = more competitive, seller-favorable market
        "description": "Average ratio of sale price to final list price.",
    },
    "Median Sale-to-List Ratio": {
        "metric": "median_sale_to_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
        "category": "Sales",
        "higher_is_better": True,  # closer to/above list = more competitive, seller-favorable market
        "description": "Median ratio of sale price to final list price.",
    },
    "Percent Sold Above List": {
        "metric": "pct_sold_above_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
        "category": "Sales",
        "higher_is_better": True,  # more sales above list = more competitive, seller-favorable market
        "description": (
            "Share of sales closing above the final list price. Sales at "
            "exactly list price are excluded."
        ),
    },
    "Percent Sold Below List": {
        "metric": "pct_sold_below_list",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
        "category": "Sales",
        "higher_is_better": False,  # more sales below list = weaker, buyer-favorable market
        "description": (
            "Share of sales closing below the final list price. Sales at "
            "exactly list price are excluded."
        ),
    },
    "For-Sale Inventory": {
        "metric": "invt_fs",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
        "category": "For-Sale Listings",
        "higher_is_better": True,  # magnitude only -- more inventory isn't clearly good or bad
        "description": "Count of unique listings active at any point during the month.",
    },
    "New Listings": {
        "metric": "new_listings",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
        "category": "For-Sale Listings",
        "higher_is_better": True,  # more new supply reads as healthy market activity
        "description": "Count of listings newly coming to market during the month.",
    },
    "Newly Pending Listings": {
        "metric": "new_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "count",
        "category": "For-Sale Listings",
        "higher_is_better": True,  # more homes going under contract reads as healthy demand
        "description": (
            "Count of listings that moved from for-sale to pending status "
            "during the period."
        ),
    },
    "Median List Price": {
        "metric": "mlp",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "dollars",
        "category": "For-Sale Listings",
        "higher_is_better": True,  # price level, magnitude only -- see ZHVI note above
        "description": "Median price at which homes were listed.",
    },
    "Share of Listings With a Price Cut": {
        "metric": "perc_listings_price_cut",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "percent",
        "category": "Price Cuts",
        "higher_is_better": False,  # more price cuts = sellers overpricing, softer demand
        "description": (
            "Unique properties whose end-of-month list price is below their "
            "start-of-month list price, divided by all unique properties "
            "with an active listing at any point that month."
        ),
    },
    "Mean Days to Pending": {
        "metric": "mean_doz_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "days",
        "category": "Days on Market",
        "higher_is_better": False,  # more days to pending = slower, colder market
        "description": (
            "Average days from first showing as for-sale to flipping to "
            "pending status. Excludes the in-contract period, unlike the "
            "older 'Days on Zillow' metric."
        ),
    },
    "Median Days to Pending": {
        "metric": "med_doz_pending",
        "cut": "uc_sfrcondo_sm_month",
        "kind": "days",
        "category": "Days on Market",
        "higher_is_better": False,  # more days to pending = slower, colder market
        "description": "Median days from for-sale to pending status.",
    },
    "Market Heat Index": {
        "metric": "market_temp_index",
        "cut": "uc_sfrcondo_month",
        "kind": "index",
        "category": "Market Heat",
        "higher_is_better": True,  # higher index = hotter, more seller-favorable market by design
        "description": (
            "Captures the balance of for-sale supply and demand in a "
            "market; a higher value means conditions favor sellers. Built "
            "from engagement and listing-performance inputs."
        ),
    },
    "Zillow Observed Rent Index (ZORI)": {
        "metric": "zori",
        "cut": "uc_sfrcondomfr_sm_sa_month",
        "kind": "dollars",
        "category": "Rentals",
        "higher_is_better": True,  # price level, magnitude only -- see ZHVI note above
        "description": (
            "Smoothed repeat-rent index of typical market-rate rent, "
            "weighted to the rental housing stock rather than only "
            "currently listed units. Dollar-denominated on the 35th-65th "
            "percentile of listed rents."
        ),
    },
    "Affordable Home Price": {
        "metric": "affordable_price",
        "cut": "downpayment_0.20_uc_sfrcondo_tier_0.33_0.67_sm_sa_month",
        "kind": "dollars",
        "category": "Affordability",
        "higher_is_better": True,  # a higher affordable-price ceiling means more homes are in reach
        "description": (
            "Home price at which the total monthly payment would stay "
            "within 30% of the median household's monthly income, assuming "
            "20% down."
        ),
    },
    "New Homeowner Income Needed": {
        "metric": "new_homeowner_income_needed",
        "cut": "downpayment_0.20_uc_sfrcondo_tier_0.33_0.67_sm_sa_month",
        "kind": "dollars",
        "category": "Affordability",
        "higher_is_better": False,  # more income required to buy = less affordable
        "description": (
            "Annual household income required to keep the total monthly "
            "payment under 30% of income after purchasing the typical home "
            "with 20% down."
        ),
    },
    "New Renter Income Needed": {
        "metric": "new_renter_income_needed",
        "cut": "uc_sfrcondomfr_sm_sa_month",
        "kind": "dollars",
        "category": "Affordability",
        "higher_is_better": False,  # more income required to rent = less affordable
        "description": (
            "Household income required to keep a newly signed lease on the "
            "typical rental under 30% of income."
        ),
    },
}

# Display order for categories in the app's dropdown (dict insertion order
# above already groups by category, but this is the explicit source of truth).
CATEGORIES = [
    "Home Values",
    "Sales",
    "For-Sale Listings",
    "Price Cuts",
    "Days on Market",
    "Market Heat",
    "Rentals",
    "Affordability",
]

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


def fetch_housing_units() -> pd.DataFrame:
    """
    County housing-unit counts (Census Vintage 2025), keyed by the same FIPS
    format as add_fips. Used to normalize count metrics -- see the URL
    comments above for why this takes two requests instead of one.
    """
    xwalk_resp = requests.get(CENSUS_FIPS_CROSSWALK_URL, timeout=60)
    xwalk_resp.raise_for_status()
    pop = pd.read_csv(
        io.BytesIO(xwalk_resp.content),
        encoding="latin1",
        usecols=["STATE", "COUNTY", "STNAME", "CTYNAME"],
    )
    pop = pop[pop["COUNTY"] != 0]  # drop state-level summary rows
    fips = pop["STATE"].astype(str).str.zfill(2) + pop["COUNTY"].astype(str).str.zfill(3)
    name_to_fips = dict(zip(zip(pop["STNAME"], pop["CTYNAME"]), fips))

    hu_resp = requests.get(CENSUS_HOUSING_UNITS_URL, timeout=60)
    hu_resp.raise_for_status()
    raw = pd.read_excel(io.BytesIO(hu_resp.content), sheet_name=0, header=None, engine="openpyxl")

    # Row 0-3 are titles/column headers, row 4 is the "United States" total;
    # county rows start at 5 and are named like ".Autauga County, Alabama".
    counties = raw.iloc[5:].copy()
    counties = counties[counties[0].astype(str).str.startswith(".")]
    names = counties[0].str[1:].str.rsplit(", ", n=1, expand=True)

    out = pd.DataFrame(
        {
            "FIPS": [name_to_fips.get(pair) for pair in zip(names[1], names[0])],
            "housing_units": counties.iloc[:, -1],  # last column = latest vintage year
        }
    )
    return out.dropna(subset=["FIPS"])


def fetch_population() -> pd.DataFrame:
    """
    County population estimates (Census Vintage 2025), keyed by the same
    FIPS format as add_fips. Used to show population in the county data
    table -- a separate request from fetch_housing_units even though both
    read the same crosswalk CSV, since population is wanted every time the
    table renders while housing units are only fetched when the normalize
    checkbox is on.
    """
    resp = requests.get(CENSUS_FIPS_CROSSWALK_URL, timeout=60)
    resp.raise_for_status()
    pop = pd.read_csv(
        io.BytesIO(resp.content),
        encoding="latin1",
        usecols=["STATE", "COUNTY", "POPESTIMATE2025"],
    )
    pop = pop[pop["COUNTY"] != 0]  # drop state-level summary rows
    fips = pop["STATE"].astype(str).str.zfill(2) + pop["COUNTY"].astype(str).str.zfill(3)
    return pd.DataFrame({"FIPS": fips, "population": pop["POPESTIMATE2025"].values})


def date_columns(df: pd.DataFrame) -> list[str]:
    """
    Every month column in a Zillow CSV, oldest to newest. Date columns look
    like '2026-07-31', so this grabs every column whose first 4 characters
    are digits -- shared by latest_value_column, prep_for_change_map, and
    the app's "Compare from" date slider, so they all agree on what counts
    as a date column.
    """
    return [c for c in df.columns if c[:4].isdigit()]


def latest_value_column(df: pd.DataFrame) -> str:
    """Find the newest month column. Don't hardcode the date -- it changes every monthly release."""
    cols = date_columns(df)
    if not cols:
        raise ValueError("No date columns found in this CSV.")
    return cols[-1]


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


def prep_for_change_map(df: pd.DataFrame, baseline_col: str) -> tuple[pd.DataFrame, str, str]:
    """
    Reduce the wide CSV to FIPS/names plus the latest value, the value as of
    `baseline_col` (a date column the app picked from date_columns(df), via
    the "Compare from" slider), and the change between them. Returns the
    tidy frame plus the baseline and latest column names, so the app can
    show what's being compared.
    """
    cols = date_columns(df)
    if not cols:
        raise ValueError("No date columns found in this CSV.")
    if baseline_col not in cols:
        raise ValueError(f"'{baseline_col}' isn't one of this file's date columns.")

    latest_col = cols[-1]
    keep = ["FIPS", "RegionName", "State", "Metro", baseline_col, latest_col]
    tidy = (
        df[keep]
        .dropna(subset=[baseline_col, latest_col])
        .rename(columns={baseline_col: "baseline_value", latest_col: "value"})
        .copy()
    )
    tidy = tidy[tidy["baseline_value"] != 0]

    # Relative % change for level metrics (dollars, counts, days, index);
    # percentage-point change for metrics already stored as a 0-1 fraction
    # (percent kind) -- diffing two percents as a relative % change reads
    # oddly (e.g. "62% -> 65%" isn't "+5%"), a point change ("+3 pp") doesn't.
    tidy["pct_change"] = (tidy["value"] - tidy["baseline_value"]) / tidy["baseline_value"] * 100
    tidy["point_change"] = (tidy["value"] - tidy["baseline_value"]) * 100
    return tidy, baseline_col, latest_col
