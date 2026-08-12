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
# steps: category first, then the metrics within it. Options for the second
# box are recomputed whenever the category changes.
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)
category = col1.selectbox("Category:", zd.CATEGORIES)
metrics_in_category = [
    label for label, spec in zd.METRICS.items() if spec["category"] == category
]
choice = col2.selectbox("Metric:", metrics_in_category)
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
