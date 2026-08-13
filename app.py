"""
app.py
------
The Streamlit web app. Run locally with:

    streamlit run app.py

It shows a dropdown of Zillow metrics and draws a county choropleth for the
one you pick. All the data work lives in zillow_data.py -- this file is just
the interface.
"""

import numpy as np
import plotly.express as px
import requests
import streamlit as st

import zillow_data as zd

# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Zillow County Choropleth", layout="wide")

# Brand colors: Zillow's blue/black two-color palette (#006AFF / #111116).
# White page background + these accents come from .streamlit/config.toml;
# this CSS only covers what the theme config can't reach -- button shape/
# hover polish and the selectbox border/focus color.
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
    div[data-baseweb="select"] > div {
        border-color: #C7DBFF;
    }
    div[data-baseweb="select"]:focus-within > div {
        border-color: #006AFF;
        box-shadow: 0 0 0 1px #006AFF;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Landing page.
#
# st.session_state persists across reruns (but resets per browser session),
# so it's what gates "have they clicked past the landing page yet." The
# button click triggers a rerun; st.rerun() forces it immediately instead of
# waiting on Streamlit's normal end-of-script rerun, so there's no flash of
# stale landing content before the main page appears.
# ---------------------------------------------------------------------------
if "entered" not in st.session_state:
    st.session_state.entered = False

if not st.session_state.entered:
    st.markdown(
        """
        <div style="text-align:center; padding-top:8rem;">
            <h1 style="color:#111116; font-size:2.75rem; margin-bottom:0.5rem;">
                Welcome to <span style="color:#006AFF;">Zillow Visualized</span>
            </h1>
            <p style="color:#5B5B66; font-size:1.15rem; margin-bottom:2.5rem;">
                Explore Zillow's housing data across every U.S. county.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, center_col, _ = st.columns([1, 1, 1])
    with center_col:
        if st.button("Click to Enter", use_container_width=True):
            st.session_state.entered = True
            st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Main page (only reached after "Click to Enter").
# ---------------------------------------------------------------------------
st.title("Zillow Housing Data by County")
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
def load_metric(metric: str, cut: str):
    df = zd.fetch_csv(metric, cut)
    return zd.prep_for_map(df)


@st.cache_data(ttl=86400)
def load_counties():
    url = (
        "https://raw.githubusercontent.com/plotly/datasets/master/"
        "geojson-counties-fips.json"
    )
    return requests.get(url, timeout=60).json()


# ---------------------------------------------------------------------------
# Controls
#
# Streamlit's selectbox has no native optgroup, so metrics are picked in two
# steps: category first, then the metrics within it. Both start with no
# selection (index=None) so the metric dropdown -- and everything below it --
# stays hidden until the user has actually picked a category, then a metric.
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)
category = col1.selectbox(
    "Category:", zd.CATEGORIES, index=None, placeholder="Select a category..."
)

choice = None
if category:
    metrics_in_category = [
        label for label, spec in zd.METRICS.items() if spec["category"] == category
    ]
    choice = col2.selectbox(
        "Metric:", metrics_in_category, index=None, placeholder="Select a metric..."
    )

if not category:
    st.info("Pick a category to begin.")
    st.stop()
if not choice:
    st.info("Pick a metric to see the map.")
    st.stop()

spec = zd.METRICS[choice]

# ---------------------------------------------------------------------------
# Load + draw
# ---------------------------------------------------------------------------
try:
    with st.spinner(f"Fetching {choice} from Zillow..."):
        tidy, month = load_metric(spec["metric"], spec["cut"])
        counties = load_counties()
except requests.HTTPError:
    st.error(
        f"Couldn't fetch '{choice}' from Zillow. The URL for this metric may "
        f"have changed. Check the tokens in zillow_data.py against the catalog."
    )
    st.stop()

# Dollar metrics look better on a log color scale (a few metros are 10x the
# rest); everything else is linear. KIND_FORMAT supplies the d3 number format
# used for the hover tooltip and, for percent metrics, the colorbar ticks.
hover_fmt = zd.KIND_FORMAT[spec["kind"]]

if spec["kind"] == "dollars":
    color_col = "log_value"
    lo, hi = tidy["log_value"].quantile([0.02, 0.98])
    ticks = [50_000, 100_000, 250_000, 500_000, 1_000_000, 2_000_000]
    ticks = [t for t in ticks if lo <= np.log10(t) <= hi]
    colorbar = dict(
        title="Value",
        tickvals=[np.log10(t) for t in ticks],
        ticktext=[f"${t:,.0f}" for t in ticks],
    )
    range_color = (lo, hi)
else:
    color_col = "value"
    colorbar = dict(title=choice)
    if spec["kind"] == "percent":
        colorbar["tickformat"] = hover_fmt
    range_color = tuple(tidy["value"].quantile([0.02, 0.98]))

fig = px.choropleth_map(
    tidy,
    geojson=counties,
    locations="FIPS",
    color=color_col,
    range_color=range_color,
    color_continuous_scale="blues",
    map_style="carto-voyager",
    zoom=3.2,
    center={"lat": 38.5, "lon": -96},
    opacity=0.75,
    hover_name="RegionName",
    custom_data=["State", "Metro", "value"],
    height=650,
)
fig.update_traces(
    marker_line_width=0,
    hovertemplate=(
        "<b>%{hovertext}</b>, %{customdata[0]}<br>"
        "%{customdata[1]}<br>"
        f"Value: %{{customdata[2]:{hover_fmt}}}<extra></extra>"
    ),
)
fig.update_layout(
    margin={"r": 0, "t": 10, "l": 0, "b": 0},
    coloraxis_colorbar=colorbar,
)

st.subheader(f"{choice} — {month}")
st.plotly_chart(fig, use_container_width=True)

st.caption(
    f"{len(tidy):,} counties shown. Values are the most recent month available "
    f"in Zillow's file ({month})."
)
