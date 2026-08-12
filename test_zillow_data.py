"""
test_zillow_data.py
--------------------
Tests for the pure data-prep functions in zillow_data.py, plus a consistency
check on the METRICS/CATEGORIES menu. Run with:

    pytest
"""

import numpy as np
import pandas as pd
import pytest
import requests

import zillow_data as zd


# ---------------------------------------------------------------------------
# add_fips
# ---------------------------------------------------------------------------

def test_add_fips_pads_and_concatenates():
    df = pd.DataFrame({
        "StateCodeFIPS": ["6", "36"],
        "MunicipalCodeFIPS": ["37", "5"],
    })
    result = zd.add_fips(df)
    assert list(result["FIPS"]) == ["06037", "36005"]


def test_add_fips_accepts_integer_codes():
    df = pd.DataFrame({
        "StateCodeFIPS": [6, 36],
        "MunicipalCodeFIPS": [37, 5],
    })
    result = zd.add_fips(df)
    assert list(result["FIPS"]) == ["06037", "36005"]


def test_add_fips_does_not_mutate_input():
    df = pd.DataFrame({"StateCodeFIPS": ["6"], "MunicipalCodeFIPS": ["37"]})
    zd.add_fips(df)
    assert "FIPS" not in df.columns


# ---------------------------------------------------------------------------
# latest_value_column
# ---------------------------------------------------------------------------

def test_latest_value_column_picks_last_date_column():
    df = pd.DataFrame(columns=["RegionName", "2026-01-31", "2026-02-28"])
    assert zd.latest_value_column(df) == "2026-02-28"


def test_latest_value_column_raises_without_date_columns():
    df = pd.DataFrame(columns=["RegionName", "State"])
    with pytest.raises(ValueError):
        zd.latest_value_column(df)


# ---------------------------------------------------------------------------
# prep_for_map
# ---------------------------------------------------------------------------

def test_prep_for_map_keeps_expected_columns_and_month():
    df = pd.DataFrame({
        "FIPS": ["06037", "36005"],
        "RegionName": ["Los Angeles County", "Bronx County"],
        "State": ["CA", "NY"],
        "Metro": ["Los Angeles-Long Beach-Anaheim, CA", "New York-Newark-Jersey City, NY-NJ-PA"],
        "2026-06-30": [900000, 500000],
        "2026-07-31": [910000, 505000],
    })
    tidy, month = zd.prep_for_map(df)
    assert month == "2026-07-31"
    assert set(tidy.columns) == {"FIPS", "RegionName", "State", "Metro", "value", "log_value"}
    assert list(tidy["value"]) == [910000, 505000]


def test_prep_for_map_drops_rows_with_missing_latest_value():
    df = pd.DataFrame({
        "FIPS": ["06037", "36005"],
        "RegionName": ["Los Angeles County", "Bronx County"],
        "State": ["CA", "NY"],
        "Metro": ["LA Metro", "NY Metro"],
        "2026-07-31": [910000, np.nan],
    })
    tidy, _ = zd.prep_for_map(df)
    assert len(tidy) == 1
    assert tidy["RegionName"].iloc[0] == "Los Angeles County"


def test_prep_for_map_log_value_matches_log10_of_value():
    df = pd.DataFrame({
        "FIPS": ["06037"],
        "RegionName": ["Los Angeles County"],
        "State": ["CA"],
        "Metro": ["LA Metro"],
        "2026-07-31": [100000],
    })
    tidy, _ = zd.prep_for_map(df)
    assert tidy["log_value"].iloc[0] == pytest.approx(5.0)  # log10(100,000) == 5


def test_prep_for_map_log_value_undefined_for_zero_or_negative():
    df = pd.DataFrame({
        "FIPS": ["06037", "36005"],
        "RegionName": ["A County", "B County"],
        "State": ["CA", "NY"],
        "Metro": ["A Metro", "B Metro"],
        "2026-07-31": [0, -5],
    })
    tidy, _ = zd.prep_for_map(df)
    assert tidy["log_value"].isna().all()


# ---------------------------------------------------------------------------
# build_url
# ---------------------------------------------------------------------------

def test_build_url_has_expected_structure():
    url = zd.build_url("zhvi", "uc_sfrcondo_tier_0.33_0.67_sm_sa_month")
    assert url.startswith(
        "https://files.zillowstatic.com/research/public_csvs/zhvi/"
        "County_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv?t="
    )


def test_build_url_respects_geography_argument():
    url = zd.build_url("zhvi", "some_cut", geography="Metro")
    assert "/Metro_zhvi_some_cut.csv" in url


# ---------------------------------------------------------------------------
# fetch_csv (network mocked -- tests must never hit the real Zillow CDN)
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def test_fetch_csv_adds_fips_column(monkeypatch):
    csv_bytes = (
        b"StateCodeFIPS,MunicipalCodeFIPS,RegionName,2026-07-31\n"
        b"6,37,Los Angeles County,910000\n"
    )
    monkeypatch.setattr(zd.requests, "get", lambda *a, **k: _FakeResponse(csv_bytes))
    df = zd.fetch_csv("zhvi", "some_cut")
    assert df["FIPS"].iloc[0] == "06037"


def test_fetch_csv_raises_http_error_on_bad_status(monkeypatch):
    monkeypatch.setattr(
        zd.requests, "get", lambda *a, **k: _FakeResponse(b"", status_code=404)
    )
    with pytest.raises(requests.HTTPError):
        zd.fetch_csv("not_a_real_metric", "some_cut")


# ---------------------------------------------------------------------------
# METRICS / CATEGORIES menu consistency
# ---------------------------------------------------------------------------

def test_every_metric_has_a_category_listed_in_categories():
    for label, spec in zd.METRICS.items():
        assert spec["category"] in zd.CATEGORIES, f"{label} has an unlisted category"


def test_every_category_has_at_least_one_metric():
    used = {spec["category"] for spec in zd.METRICS.values()}
    for category in zd.CATEGORIES:
        assert category in used, f"{category} has no metrics"


def test_every_metric_has_required_keys():
    required = {"metric", "cut", "kind", "category"}
    for label, spec in zd.METRICS.items():
        assert required.issubset(spec.keys()), f"{label} missing keys"


def test_every_metric_kind_has_a_display_format():
    for label, spec in zd.METRICS.items():
        assert spec["kind"] in zd.KIND_FORMAT, f"{label} has an unformattable kind '{spec['kind']}'"
