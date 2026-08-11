# Zillow Research — Metric Dictionary

Source: Zillow Research Housing Data (https://www.zillow.com/research/data/)
Slugs correspond to CSV file paths under `files.zillowstatic.com/research/public_csvs/<slug>/`.

| # | Slug | Metric | Category | Description |
|---|---|---|---|---|
| 1 | `zhvi` | Zillow Home Value Index | Home values | Typical home value and market change for a region and housing type, reflecting the 35th–65th percentile of values. Represents the whole housing stock, not just homes that sold — it is not a median sale price. |
| 2 | `invt_fs` | For-Sale Inventory | For-sale listings | Count of unique listings active at any point during the month. |
| 3 | `mean_sale_to_list` | Mean Sale-to-List Ratio | Sales | Average ratio of sale price to final list price. |
| 4 | `mean_doz_pending` | Mean Days to Pending | Days on market | Average days from first showing as for-sale to flipping to pending status. Excludes the in-contract period, unlike the older "Days on Zillow" metric. |
| 5 | `med_doz_pending` | Median Days to Pending | Days on market | Median days from for-sale to pending status. |
| 6 | `market_temp_index` | Market Heat Index | Market heat | Captures the balance of for-sale supply and demand in a market; a higher value means conditions favor sellers. Built from engagement and listing-performance inputs. |
| 7 | `sales_count_now` | Sales Count (Nowcast) | Sales | Estimated number of unique properties sold during the month. The latest month is an estimate accounting for the lag between when sales occur and when they are reported. |
| 8 | `median_sale_price` | Median Sale Price | Sales | Median price at which homes sold. Latest month is nowcast to account for sales-reporting latency. |
| 9 | `mlp` | Median List Price | For-sale listings | Median price at which homes were listed. |
| 10 | `median_sale_to_list` | Median Sale-to-List Ratio | Sales | Median ratio of sale price to final list price. |
| 11 | `new_pending` | Newly Pending Listings | For-sale listings | Count of listings that moved from for-sale to pending status during the period. |
| 12 | `perc_listings_price_cut` | Share of Listings With a Price Cut | Price cuts | Unique properties whose end-of-month list price is below their start-of-month list price, divided by all unique properties with an active listing at any point that month. |
| 13 | `pct_sold_above_list` | Percent Sold Above List | Sales | Share of sales closing above the final list price. Sales at exactly list price are excluded. |
| 14 | `new_listings` | New Listings | For-sale listings | Count of listings newly coming to market during the month. |
| 15 | `pct_sold_below_list` | Percent Sold Below List | Sales | Share of sales closing below the final list price. Sales at exactly list price are excluded. |
| 16 | `new_con_sales_count_raw` | New Construction Sales Count | New construction | Unique new-construction homes sold during the month. Note: as of Aug 2025 the definition was widened to include homes at all construction stages — a definitional break in the series. |
| 17 | `zori` | Zillow Observed Rent Index | Rentals | Smoothed repeat-rent index of typical market-rate rent, weighted to the rental housing stock rather than only currently listed units. Dollar-denominated on the 35th–65th percentile of listed rents. |
| 18 | `new_homeowner_income_needed` | New Homeowner Income Needed | Affordability | Annual household income required to keep the total monthly payment under 30% of income after purchasing the typical home with 20% down. |
| 19 | `new_renter_income_needed` | New Renter Income Needed | Affordability | Household income required to keep a newly signed lease on the typical rental under 30% of income. |
| 20 | `affordable_price` | Affordable Home Price | Affordability | Home price at which the total monthly payment would stay within 30% of the median household's monthly income, assuming 20% down. |
| 21 | `zhvf_growth` | Zillow Home Value Forecast (growth) | Forecasts | Month-, quarter- and year-ahead forecast of ZHVI, built off the all-homes mid-tier cut. Published as MoM / QoQ / YoY percentages, not as a level. |
| 22 | `zorf_growth` | Zillow Observed Rent Forecast (growth) | Forecasts | Month-, quarter- and year-ahead forecast of ZORI, also published as growth rates. |

## Usage notes

- **Column interpretation of the source inventory:** columns 2 and 3 multiply to column 6, read as *(data-type variants) × (geography levels) = total CSV files*, with column 7 as file size in MB.
- **Revision risk:** the sale-side metrics (`sales_count_now`, `median_sale_price`, `new_con_sales_count_raw`) are nowcast / latency-adjusted, so the most recent month revises. Zillow publishes these on the 16th of each month; a mid-cycle snapshot will not tie to a later refresh.
- **Update cadence:** monthly data refreshes on the 16th; most weekly data refreshes on Tuesdays. Some metrics are published at both weekly and monthly cadence, which drives much of the file-count variation.
- **Series break:** `new_con_sales_count_raw` is not comparable pre- and post-Aug 2025 without adjustment.
