"""
app.py
------
The Streamlit web app. Run locally with:

    streamlit run app.py

It shows a dropdown of Zillow metrics and draws a county choropleth for the
one you pick. All the data work lives in zillow_data.py -- this file is just
the interface.
"""

from datetime import datetime

import numpy as np
import plotly.express as px
import requests
import streamlit as st

import zillow_data as zd

# Trim quantile for the color range on every metric kind -- keeps a handful of
# extreme counties from washing out the scale for everyone else. Shared by
# both branches below so the two "clip to the middle 96%" decisions don't
# drift apart into two different policies.
CLIP_QUANTILES = (0.02, 0.98)

# Soft red/white/green scale for the data table's conditional formatting
# (Google Sheets' default color-scale palette) -- deliberately gentler than
# the map's own diverging colors, since a full-cell background fill reads
# more intensely than the same color on a thin map polygon.
TABLE_GRADIENT_STOPS = ["#F4C7C3", "#FFFFFF", "#B7E1CD"]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def _interpolate_color(t: float, stops: list[str]) -> str:
    """t in [0, 1] -> a hex color interpolated across `stops` (evenly spaced)."""
    t = min(max(t, 0.0), 1.0)
    n = len(stops) - 1
    idx = min(int(t * n), n - 1)
    local_t = t * n - idx
    c0, c1 = _hex_to_rgb(stops[idx]), _hex_to_rgb(stops[idx + 1])
    r, g, b = (round(c0[i] + (c1[i] - c0[i]) * local_t) for i in range(3))
    return f"#{r:02X}{g:02X}{b:02X}"


def _text_color_for(hex_color: str) -> str:
    """White text on dark backgrounds, near-black text on light ones."""
    r, g, b = _hex_to_rgb(hex_color)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#FFFFFF" if luminance < 140 else "#111116"


def conditional_background(series, stops: list[str], vmin: float, vmax: float) -> list[str]:
    """
    Per-cell 'background-color: ...; color: ...' CSS for a pandas Styler,
    scaling `series` linearly across `stops` between vmin and vmax. Used to
    color the data table's primary metric column with the same palette the
    map itself uses, so the two stay visually tied together.
    """
    span = vmax - vmin or 1
    styles = []
    for v in series:
        if v is None or v != v:  # NaN check without importing pandas here
            styles.append("")
            continue
        t = (v - vmin) / span
        bg = _interpolate_color(t, stops)
        styles.append(f"background-color: {bg}; color: {_text_color_for(bg)}")
    return styles


def log_ticks(lo: float, hi: float) -> list[int]:
    """
    'Nice' 1/2/5-per-decade tick values spanning a log10(lo)-log10(hi) range.

    Dollar metrics span very different scales -- ZORI rent is ~$800-$3,000,
    ZHVI home values are ~$90k-$700k -- so a fixed tick ladder sized for one
    of them leaves the other with an empty (or nearly empty) colorbar. This
    generates ticks from the metric's own range instead.
    """
    ticks = []
    for decade in range(int(np.floor(lo)), int(np.ceil(hi)) + 1):
        for base in (1, 2, 5):
            t = base * 10**decade
            if lo <= np.log10(t) <= hi:
                ticks.append(t)
    return ticks

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Zillow County Choropleth", layout="wide")

# Brand colors: Zillow's blue/black two-color palette (#006AFF / #111116).
# The overall page canvas + sidebar colors come from .streamlit/config.toml
# (light gray page, white sidebar/cards); this CSS mimics the rest of
# Zillow's actual product chrome -- pill-shaped filter controls, a
# segmented-control toggle, and white cards with soft shadows floating on
# the gray canvas, the way listing cards float on their search page.
st.markdown(
    """
    <style>
    div.stButton > button {
        background-color: #006AFF;
        color: #FFFFFF;
        border: none;
        border-radius: 999px;
        padding: 0.75rem 2.5rem;
        font-size: 1.05rem;
        font-weight: 600;
        box-shadow: 0 4px 14px rgba(0, 106, 255, 0.25);
        transition: transform 0.15s ease, box-shadow 0.15s ease,
            background-color 0.15s ease;
    }
    div.stButton > button:hover {
        background-color: #0057D9;
        color: #FFFFFF;
        transform: translateY(-2px);
        box-shadow: 0 6px 18px rgba(0, 106, 255, 0.35);
    }
    div.stButton > button:active {
        transform: translateY(0);
    }
    /* Pill-shaped selects, like Zillow's "Price", "Beds & Baths" filter chips. */
    div[data-baseweb="select"] > div {
        border-color: #C7DBFF;
        border-radius: 999px;
    }
    div[data-baseweb="select"]:focus-within > div {
        border-color: #006AFF;
        box-shadow: 0 0 0 1px #006AFF;
    }
    ul[data-baseweb="menu"] {
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(17, 17, 22, 0.12);
    }
    /* Segmented "View" control, like Zillow's For Sale / For Rent toggle. */
    div[data-testid="stSegmentedControl"] div[role="radiogroup"] {
        background-color: #EAF2FF;
        border-radius: 999px;
        padding: 4px;
        gap: 4px;
    }
    div[data-testid="stSegmentedControl"] label {
        border-radius: 999px !important;
        border: none !important;
    }
    section[data-testid="stSidebar"] {
        border-right: 1px solid #E2E5EA;
    }
    /* Streamlit reserves ~6rem of top padding for its header toolbar by
       default, which reads as a big empty gap above the content -- trim it
       down while still clearing the toolbar (hamburger/deploy button). */
    div[data-testid="stMainBlockContainer"] {
        padding-top: 2rem;
    }
    section[data-testid="stSidebar"] div[data-testid="stMainBlockContainer"] {
        padding-top: 1.5rem;
    }
    .st-key-map-card, .st-key-table-card {
        background-color: #FFFFFF;
        border-radius: 16px;
        box-shadow: 0 2px 12px rgba(17, 17, 22, 0.08);
        padding: 1.5rem;
    }
    /* Sidebar is already white, so the about box gets a tinted background
       (rather than white-on-white) to still read as its own card. */
    .st-key-about-card {
        background-color: #EAF2FF;
        border-radius: 12px;
        border-left: 4px solid #006AFF;
        padding: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Main page.
#
# A small header bar (logo mark + wordmark) instead of a plain st.title, in
# the spirit of Zillow's own top nav -- a compact brand lockup rather than a
# generic page heading.
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div style="display:flex; align-items:center; gap:0.65rem; padding-bottom:0.25rem;">
        <div style="
            background-color:#006AFF; color:#FFFFFF; font-weight:800;
            width:38px; height:38px; border-radius:999px;
            display:flex; align-items:center; justify-content:center;
            font-size:1.15rem; flex-shrink:0;
        ">Z</div>
        <div style="font-size:1.6rem; font-weight:700; color:#111116;">
            Zillow Housing Data <span style="color:#006AFF;">by County</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption("Data: Zillow Research (files.zillowstatic.com). Monthly series.")


# ---------------------------------------------------------------------------
# Cached loaders.
#
# @st.cache_data means Streamlit remembers the result so it doesn't re-download
# the same file every time someone clicks. ttl=86400 seconds = refresh once a
# day, which is how we "routinely bring in the newest data" without a scheduled
# job. Change ttl to fetch more or less often.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def load_raw(metric: str, cut: str):
    return zd.fetch_csv(metric, cut)


def fmt_month(date_str: str) -> str:
    """'2026-07-31' -> 'Jul-31-2026', for display in the subheader/caption."""
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b-%d-%Y")


@st.cache_data(ttl=86400)
def load_counties():
    url = (
        "https://raw.githubusercontent.com/plotly/datasets/master/"
        "geojson-counties-fips.json"
    )
    return requests.get(url, timeout=60).json()


# Housing-unit estimates are an annual Census release, not a monthly one like
# the Zillow files above -- a 30-day TTL avoids re-downloading and re-parsing
# the XLSX on every rerun for data that doesn't change day to day.
@st.cache_data(ttl=30 * 86400)
def load_housing_units():
    return zd.fetch_housing_units()


@st.cache_data(ttl=30 * 86400)
def load_population():
    return zd.fetch_population()


# Metric kinds where a raw count mostly just reflects county population size
# (For-Sale Inventory, New Listings, Newly Pending Listings) -- these are the
# ones where normalizing by housing units makes the map comparable across
# counties instead of just re-drawing the population map.
NORMALIZABLE_KINDS = {"count"}


# ---------------------------------------------------------------------------
# Controls (sidebar).
#
# Streamlit's selectbox has no native optgroup, so metrics are picked in two
# steps: category first, then the metrics within it. The app lands on ZHVI
# (Home Values) by default; switching to a different category clears the
# metric dropdown until a metric within it is picked. Controls live in the
# sidebar rather than inline columns so the map gets the full page width and
# the filter/result split reads as a dashboard rather than a form.
# ---------------------------------------------------------------------------
DEFAULT_CATEGORY = "Home Values"
DEFAULT_METRIC = "Typical Home Value (ZHVI)"

with st.sidebar:
    st.header("Filters")

    category = st.selectbox(
        "Category:", zd.CATEGORIES, index=zd.CATEGORIES.index(DEFAULT_CATEGORY)
    )

    metrics_in_category = [
        label for label, spec in zd.METRICS.items() if spec["category"] == category
    ]
    default_metric_index = (
        metrics_in_category.index(DEFAULT_METRIC) if category == DEFAULT_CATEGORY else None
    )
    choice = st.selectbox(
        "Metric:",
        metrics_in_category,
        index=default_metric_index,
        placeholder="Select a metric...",
    )

    if not choice:
        st.info("Pick a metric to see the map.")
        st.stop()

    spec = zd.METRICS[choice]

    # Fetched here (rather than down in "Load + draw") because the "Compare
    # from" slider below needs to know this metric's actual available dates
    # -- they vary by metric, so the slider can't be built until this loads.
    try:
        raw_df = load_raw(spec["metric"], spec["cut"])
    except requests.HTTPError:
        st.error(
            f"Couldn't fetch '{choice}' from Zillow. The URL for this metric may "
            f"have changed. Check the tokens in zillow_data.py against the catalog."
        )
        st.stop()

    st.divider()
    view = st.segmented_control(
        "View:",
        ["Latest Value", "Change Over Time"],
        default="Latest Value",
        selection_mode="single",
        required=True,
        help=(
            "Latest Value colors counties by the most recent month. Change "
            "Over Time colors them by how much the value moved between the "
            "latest month and a date you choose."
        ),
    )

    baseline_col = None
    if view == "Change Over Time":
        # Every date but the latest -- comparing the latest month to itself
        # isn't a meaningful change.
        from_options = zd.date_columns(raw_df)[:-1]
        if not from_options:
            st.warning(f"{choice} doesn't have enough history yet for a Change Over Time comparison.")
            st.stop()

        # A slider spanning 20+ years of monthly steps is precise but fiddly
        # to land on a specific point -- these buttons jump straight to a
        # preset lookback by writing into the slider's own session_state key
        # *before* it's instantiated below, which is how Streamlit lets a
        # button set another widget's value.
        def _jump_to(months_back: int) -> None:
            idx = max(0, len(from_options) - months_back)
            st.session_state["compare_from_slider"] = from_options[idx]

        preset_cols = st.columns(5)
        for col, (label, months) in zip(
            preset_cols, [("1M", 1), ("3M", 3), ("6M", 6), ("1Y", 12), ("5Y", 60)]
        ):
            col.button(label, on_click=_jump_to, args=(months,), width="stretch")

        # Streamlit forbids passing both `value` and pre-setting the same
        # key in session_state (it can't tell which should win) -- so the
        # ~1-year-back default is seeded into session_state only once, the
        # first time this widget key is ever created, and `value` is never
        # passed at all.
        if "compare_from_slider" not in st.session_state:
            st.session_state["compare_from_slider"] = from_options[max(0, len(from_options) - 12)]
        baseline_col = st.select_slider(
            "Compare from:",
            options=from_options,
            format_func=fmt_month,
            key="compare_from_slider",
        )

    # Normalizing by housing units only applies to the Latest Value view --
    # a % change is already relative to that county's own baseline, so it's
    # comparable across counties of any size without a separate normalization.
    normalize_by_units = False
    if view == "Latest Value" and spec["kind"] in NORMALIZABLE_KINDS:
        normalize_by_units = st.checkbox(
            "Normalize by housing units (per 1,000 units)",
            help=(
                "Raw counts mostly track how big a county's housing stock is. "
                "This divides by each county's total housing units (Census "
                "Bureau, Vintage 2025 estimate) so counties of different sizes "
                "are comparable on the map."
            ),
        )

    st.divider()
    with st.container(border=True, key="about-card"):
        st.markdown(f"**About {choice}**")
        st.markdown(
            f'<span style="color:#5B5B66; font-size:0.9rem; line-height:1.5;">'
            f'{spec["description"]}</span>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# Load + draw
# ---------------------------------------------------------------------------
try:
    with st.spinner(f"Loading {choice}..."):
        # raw_df was already fetched in the sidebar (the "Compare from"
        # slider needed its date columns); reused here rather than fetched
        # again.
        counties = load_counties()
        # Measured against every county the map *could* draw (the geojson),
        # not the metric's own file size -- some metrics (e.g. Mean Days to
        # Pending) only cover ~1,500 of ~3,200 counties in Zillow's own data,
        # and comparing a file's row count to itself always reads as ~100%,
        # hiding exactly the coverage gap this number is meant to surface.
        total_counties = len(counties["features"])
        if view == "Change Over Time":
            tidy, baseline_col, latest_col = zd.prep_for_change_map(raw_df, baseline_col)
            baseline_month, latest_month = fmt_month(baseline_col), fmt_month(latest_col)
        else:
            tidy, latest_col = zd.prep_for_map(raw_df)
            latest_month = fmt_month(latest_col)
            if normalize_by_units:
                housing_units = load_housing_units()
                tidy = tidy.merge(housing_units, on="FIPS", how="inner")
                tidy = tidy[tidy["housing_units"] > 0]
                tidy["per_1000_units"] = tidy["value"] / tidy["housing_units"] * 1000
except requests.HTTPError:
    st.error(
        f"Couldn't fetch '{choice}' from Zillow. The URL for this metric may "
        f"have changed. Check the tokens in zillow_data.py against the catalog."
    )
    st.stop()
except ValueError as e:
    st.error(f"Can't show that comparison for {choice}: {e}")
    st.stop()

# ~40% of counties have no assigned metro area, so Zillow's Metro column is
# NaN for them -- without this, the hover tooltip's second line would
# literally read "nan" for those counties instead of something legible.
tidy["Metro"] = tidy["Metro"].fillna("Not in a metro area")

# KIND_FORMAT supplies the d3 number format for the *raw* value, used in the
# hover tooltip (and, outside the change view, the colorbar ticks too).
hover_fmt = zd.KIND_FORMAT[spec["kind"]]

# A red -> neutral gray -> green diverging scale for the change view, so a
# 0% move sits on a neutral midpoint instead of a color implying direction.
# For metrics where a decrease is the good outcome (days on market, price
# cuts, income needed, ...), the scale is flipped so green still means
# "moved the right way" rather than always meaning "went up."
DIVERGING_SCALE_UP_GOOD = [(0.0, "#C0362C"), (0.5, "#E8E8EA"), (1.0, "#1E8E3E")]
DIVERGING_SCALE_DOWN_GOOD = [(0.0, "#1E8E3E"), (0.5, "#E8E8EA"), (1.0, "#C0362C")]

if view == "Change Over Time":
    # Percent-kind metrics are already a 0-1 fraction, so their "change" is
    # shown in percentage points (+3 pp), not a relative % change of a %.
    is_percent_kind = spec["kind"] == "percent"
    color_col = "point_change" if is_percent_kind else "pct_change"
    change_fmt = "+.1f"
    change_suffix = " pp" if is_percent_kind else "%"
    bound = float(tidy[color_col].abs().quantile(CLIP_QUANTILES[1]))
    range_color = (-bound, bound)
    color_scale = DIVERGING_SCALE_UP_GOOD if spec["higher_is_better"] else DIVERGING_SCALE_DOWN_GOOD
    colorbar = dict(
        title="Point Change" if is_percent_kind else "% Change",
        tickformat=change_fmt,
        ticksuffix=change_suffix,
    )
elif normalize_by_units:
    color_col = "per_1000_units"
    hover_fmt = ",.1f"
    color_scale = "blues"
    colorbar = dict(title="Per 1,000 Units", tickformat=hover_fmt)
    range_color = tuple(tidy["per_1000_units"].quantile(CLIP_QUANTILES))
elif spec["kind"] == "dollars":
    color_col = "log_value"
    color_scale = "blues"
    lo, hi = tidy["log_value"].quantile(CLIP_QUANTILES)
    ticks = log_ticks(lo, hi)
    colorbar = dict(
        title="Value",
        tickvals=[np.log10(t) for t in ticks],
        ticktext=[f"${t:,.0f}" for t in ticks],
    )
    range_color = (lo, hi)
else:
    color_col = "value"
    color_scale = "blues"
    colorbar = dict(title="Value", tickformat=hover_fmt)
    range_color = tuple(tidy["value"].quantile(CLIP_QUANTILES))

if view == "Change Over Time":
    custom_data = ["State", "Metro", color_col, "baseline_value", "value"]
elif normalize_by_units:
    custom_data = ["State", "Metro", "per_1000_units", "value"]
else:
    custom_data = ["State", "Metro", "value"]

fig = px.choropleth_map(
    tidy,
    geojson=counties,
    locations="FIPS",
    color=color_col,
    range_color=range_color,
    color_continuous_scale=color_scale,
    map_style="carto-voyager",
    zoom=3.2,
    center={"lat": 38.5, "lon": -96},
    opacity=0.75,
    hover_name="RegionName",
    custom_data=custom_data,
    height=650,
)
if view == "Change Over Time":
    hovertemplate = (
        "<b>%{hovertext}</b>, %{customdata[0]}<br>"
        "%{customdata[1]}<br>"
        f"Change: %{{customdata[2]:{change_fmt}}}{change_suffix}<br>"
        f"{baseline_month}: %{{customdata[3]:{hover_fmt}}}<br>"
        f"{latest_month}: %{{customdata[4]:{hover_fmt}}}<extra></extra>"
    )
elif normalize_by_units:
    raw_hover_fmt = zd.KIND_FORMAT[spec["kind"]]
    hovertemplate = (
        "<b>%{hovertext}</b>, %{customdata[0]}<br>"
        "%{customdata[1]}<br>"
        f"Per 1,000 Units: %{{customdata[2]:{hover_fmt}}}<br>"
        f"Raw Count: %{{customdata[3]:{raw_hover_fmt}}}<extra></extra>"
    )
else:
    hovertemplate = (
        "<b>%{hovertext}</b>, %{customdata[0]}<br>"
        "%{customdata[1]}<br>"
        f"Value: %{{customdata[2]:{hover_fmt}}}<extra></extra>"
    )
fig.update_traces(marker_line_width=0, hovertemplate=hovertemplate)
fig.update_layout(
    margin={"r": 0, "t": 10, "l": 0, "b": 0},
    coloraxis_colorbar=colorbar,
)
# Caps how far a viewer can scroll/pinch-zoom out: MapLibre won't let the
# viewport show area outside these bounds, so zooming out bottoms out at
# roughly "all of North America" instead of the whole globe.
fig.update_maps(bounds={"west": -170, "east": -50, "south": 5, "north": 75})

# Map, subheader, and caption sit in a white card floating on the gray page
# canvas -- the "st-key-map-card" hook lets the CSS block above style this
# specific container (Streamlit generates that class name from the `key`).
with st.container(border=True, key="map-card"):
    if view == "Change Over Time":
        st.subheader(f"{choice} — Change from {baseline_month} to {latest_month}")
    else:
        title_suffix = " (per 1,000 housing units)" if normalize_by_units else ""
        st.subheader(f"{choice}{title_suffix} — {latest_month}")

    # A key tied to everything that changes the color scale forces Streamlit
    # to fully remount the chart on those changes rather than asking
    # Plotly.js to patch the existing instance in place -- without this, the
    # color axis (range/scale) can visibly lag a render behind when swapping
    # between, say, a Change Over Time diverging scale and a Latest Value
    # sequential one.
    chart_key = f"choropleth-{choice}-{view}-{baseline_col}-{normalize_by_units}"
    st.plotly_chart(fig, width="stretch", key=chart_key)

    if view == "Change Over Time":
        st.caption(
            f"{len(tidy):,} counties out of {total_counties:,} shown. "
            f"Comparing {baseline_month} to {latest_month}."
        )
    else:
        normalization_note = (
            " Normalized using Census Bureau Vintage 2025 county housing-unit estimates."
            if normalize_by_units
            else ""
        )
        st.caption(
            f"{len(tidy):,} counties out of {total_counties:,} shown. Values are the "
            f"most recent month available in Zillow's file ({latest_month})."
            f"{normalization_note}"
        )

# State-level data table (average of each state's counties) instead of a
# 3,000+ row county table, plus a county lookup dropdown -- sorted by
# population, so the biggest counties are at the top instead of buried
# alphabetically -- for drilling into one county without scrolling.
KIND_COLUMN_FORMAT = {
    "dollars": "dollar",
    "percent": "percent",
    "count": "localized",
    "days": "localized",
    "index": "localized",
}
value_format = KIND_COLUMN_FORMAT[spec["kind"]]

# County population (Census Vintage 2025) -- used both to sum up a per-state
# population column and to sort the county lookup dropdown. Best effort: if
# the Census fetch fails, degrade gracefully rather than breaking the page.
try:
    tidy = tidy.merge(load_population(), on="FIPS", how="left")
    has_population = True
except requests.RequestException:
    has_population = False

if view == "Change Over Time":
    avg_label = "Avg Change"
    agg_col = color_col
    avg_format = "%.1f pp" if is_percent_kind else "%.1f%%"
elif normalize_by_units:
    avg_label = "Avg Per 1,000 Units"
    agg_col = "per_1000_units"
    avg_format = "%.1f"
else:
    avg_label = "Avg Value"
    agg_col = "value"
    avg_format = value_format

agg_spec = {agg_col: "mean", "RegionName": "count"}
if has_population:
    agg_spec["population"] = "sum"

state_rename = {agg_col: avg_label, "RegionName": "Counties", "population": "Population"}
state_table = (
    tidy.groupby("State", as_index=False)
    .agg(agg_spec)
    .rename(columns=state_rename)
    .sort_values(avg_label, ascending=False)
    .reset_index(drop=True)  # so the index lines up with the grid's displayed row position
)

state_column_config = {
    avg_label: st.column_config.NumberColumn(format=avg_format),
    "Counties": st.column_config.NumberColumn(format="localized"),
}
if has_population:
    state_column_config["Population"] = st.column_config.NumberColumn(format="localized")

# Conditional formatting on the state average column -- same soft red/white/
# green scale as before, but ranged off the state-level averages themselves
# (averaging smooths out the extremes a single county can hit, so reusing
# the map's per-county range would leave almost every state looking neutral).
# Reversed for metrics where a lower number is the healthier-market outcome
# (days on market, price cuts, income needed, ...), so green consistently
# means "moved/sits the right way," not just "higher magnitude."
if view == "Change Over Time":
    state_bound = state_table[avg_label].abs().max()
    state_vmin, state_vmax = -state_bound, state_bound
else:
    state_vmin, state_vmax = state_table[avg_label].min(), state_table[avg_label].max()

table_stops = TABLE_GRADIENT_STOPS if spec["higher_is_better"] else list(reversed(TABLE_GRADIENT_STOPS))

# Read the state table's selection from *before* this rerun (it persists in
# session_state under its widget key) so the clicked row can be highlighted
# in the very same render that draws it, rather than one click behind.
prior_state_selection = st.session_state.get("state_table", {})
prior_cells = (prior_state_selection or {}).get("selection", {}).get("cells", [])
# Each cell is a (row, column) pair -- a tuple via the typed selection API,
# a plain [row, column] list when read straight out of session_state like
# this -- either way the row position is the first element, not a "row" key.
selected_row_idx = prior_cells[0][0] if prior_cells else None


def highlight_selected_row(row):
    if selected_row_idx is not None and row.name == selected_row_idx:
        return ["background-color: #C7DBFF"] * len(row)
    return [""] * len(row)


styled_state_table = state_table.style.apply(
    conditional_background,
    stops=table_stops,
    vmin=state_vmin,
    vmax=state_vmax,
    subset=[avg_label],
).apply(highlight_selected_row, axis=1)

with st.container(border=True, key="table-card"):
    header_col, download_col = st.columns([4, 1])
    header_col.subheader(f"{choice} - State Data")

    view_slug = "change" if view == "Change Over Time" else "latest"
    csv_bytes = state_table.to_csv(index=False).encode("utf-8")
    download_col.download_button(
        "Download CSV",
        data=csv_bytes,
        file_name=f"{spec['metric']}_{view_slug}_by_state_{latest_month}.csv",
        mime="text/csv",
    )

    # st.dataframe has no native expandable/nested rows, so "click a state to
    # see its counties" is built with selection instead: clicking a cell
    # reruns the app with that row's index, and the county breakdown for it
    # renders directly below -- same effect, without a separate dropdown.
    # Cell selection (rather than row selection) is deliberate: row-selection
    # mode draws a checkbox gutter column that cell selection doesn't, and
    # the click still resolves to a row via the cell's (row, column) pair
    # either way -- the selected row itself is highlighted above via the
    # Styler instead.
    selection = st.dataframe(
        styled_state_table,
        hide_index=True,
        width="stretch",
        height=320,
        column_config=state_column_config,
        on_select="rerun",
        selection_mode="single-cell",
        key="state_table",
    )

    selected_cells = selection.selection.cells if selection and selection.selection else []
    if selected_cells:
        selected_state = state_table.iloc[selected_cells[0][0]]["State"]

        if view == "Change Over Time":
            county_change_label = "Change (pp)" if is_percent_kind else "Change (%)"
            county_cols = ["RegionName", "baseline_value", "value", color_col]
            county_rename = {
                "RegionName": "County",
                "baseline_value": baseline_month,
                "value": latest_month,
                color_col: county_change_label,
            }
            county_column_config = {
                baseline_month: st.column_config.NumberColumn(format=value_format),
                latest_month: st.column_config.NumberColumn(format=value_format),
                county_change_label: st.column_config.NumberColumn(format="%.1f"),
            }
        elif normalize_by_units:
            county_cols = ["RegionName", "value", "per_1000_units"]
            county_rename = {"RegionName": "County", "value": "Raw Count", "per_1000_units": "Per 1,000 Units"}
            county_column_config = {
                "Raw Count": st.column_config.NumberColumn(format=value_format),
                "Per 1,000 Units": st.column_config.NumberColumn(format="%.1f"),
            }
        else:
            county_cols = ["RegionName", "value"]
            county_rename = {"RegionName": "County", "value": "Value"}
            county_column_config = {"Value": st.column_config.NumberColumn(format=value_format)}

        if has_population:
            county_cols.append("population")
            county_rename["population"] = "Population"
            county_column_config["Population"] = st.column_config.NumberColumn(format="localized")

        fallback_sort_col = county_rename[county_cols[1]]
        county_table = (
            tidy.loc[tidy["State"] == selected_state, county_cols]
            .rename(columns=county_rename)
            .sort_values("Population" if has_population else fallback_sort_col, ascending=False)
        )

        st.divider()
        st.markdown(f"**Counties in {selected_state}, sorted by population**")
        st.dataframe(
            county_table, hide_index=True, width="stretch", height=250, column_config=county_column_config
        )
