# Methodology and definitions — F02 / F05

Staged note. Definitions only. No new claims about results: no thesis
result has been recomputed in Stage 1 (real-data execution is BLOCKED;
see `STAGE1_CLOSEOUT_REPORT.md`).

## 1. Primary evaluation window

- **7300-day horizon:** days **6200–7299 inclusive** (the test period
  after training 0–5099 and validation 5100–6199).
- **Short-horizon runner:** the window is per-horizon — 1500–1999
  (2000-day), 2250–2999 (3000-day), 4000–4999 (5000-day).
- The window is **shared across all scenarios and models** within a
  horizon. Comparisons across scenarios or models are only valid over
  the same period. The F01 error was exactly this: Combined inventory
  was aggregated over the full horizon while Normal/Demand/Supply used
  the test window, making Combined-vs-other comparisons invalid as
  presented. The F01 recomputation script (`scripts/recompute_inventory_windows.py`)
  enforces one common window for all scenarios and models.

## 2. Full-horizon totals vs test-window metrics

- **Full-horizon demand** (e.g. 75,262,671 Normal/Supply;
  101,932,845 Demand/Combined over 7300 days) is a **separately
  labelled descriptive total** (`full_horizon_demand`). It is never a
  denominator of a test-window metric and never mixed into
  test-window comparisons.
- The locked table's `total_demand` column is full-horizon for all
  scenarios while most other locked inventory metrics are test-window
  (F02). The correction is to report test-window demand
  (11,899,428 Normal/Supply; 17,182,745 Demand/Combined) as the
  primary denominator and keep full-horizon demand as context.

## 3. Forecast metrics (F05) — one consistent definition

Per item, over the same test window:

- **MAE** = mean |actual − forecast|.
- **RMSE** = sqrt(mean (actual − forecast)²).
- **MASE** = item MAE / item training-period naïve seasonal-error
  scale, where the scale = mean |train[7:] − train[−7:]| over that
  item's training series (days 0–6199 for the 7300-day horizon;
  pre-test data for the runner). This matches the primary
  implementation (notebook cells 67, 81, 89; runner).
- **Aggregation: mean across items.** Pooled errors (all rows pooled)
  and pooled MASE are never substituted. Under complete coverage,
  pooled MAE equals mean-of-item MAE (equal rows per item), but pooled
  RMSE and pooled MASE generally differ from mean-of-item values; the
  F05 script's synthetic tests prove it uses the mean-of-item values.
  **Median-of-item ranks** are computed as a separate F03 sensitivity
  analysis (see §5.1), labelled as sensitivity; the primary analysis
  uses mean-of-item ranks.
- MASE denominator must be > 0 per item; a zero denominator (exactly
  7-periodic training series) is an explicit error, not a silent NaN.
- **Finite values.** Non-finite forecast/actual/demand values (NaN,
  ±inf) are rejected explicitly by the F05 script, the F03 script,
  and the runner; they must never silently produce a metric or rank.

## 4. Fill-rate / unfilled-demand identity (F02)

- Per (day, item), the simulator guarantees
  `served + unfilled = demand` (base simulator `step()` stage 4:
  if on-hand ≥ demand, served = demand, unfilled = 0; else served =
  on-hand, unfilled = demand − on-hand; integer arithmetic).
- Therefore, **only when unfilled demand and total demand refer to
  the same window and the same population**:
  `fill_rate = 1 − total_unfilled_demand / total_demand`
  (subject only to floating-point presentation).
- The identity FAILS if the two quantities come from different
  windows (the F02 error) or different populations. The F01 script
  verifies the identity per scenario/model and fails explicitly if
  it does not hold.
- Do not arithmetically reconcile fill rate with unfilled demand
  across mixed windows in thesis prose.

## 5. Forecast and inventory ranking direction

### 5.1 Inventory aggregation (v2 — daily aggregates)

Inventory and backlog levels are DAILY AGGREGATES
(aggregation version `inventory-metrics-v2-daily-aggregate`, used by
both the short-horizon runner and the F01 recomputation script):

- **Destination inventory:** sum of `on_hand` across items at the
  destination node, per day; mean and maximum across test days.
- **Destination backlog:** sum of `backlog` across items at the
  destination node, per day; mean, maximum, and final (last test
  day) across test days.
- **Network inventory:** sum of `on_hand` across all nodes and items,
  per day; mean and maximum across test days.

This matches the 7,300-day notebook's aggregation (groupby day, sum,
then mean/max). Earlier versions of the runner and the F01 script
used per-row (day, item) means and single-record maxima; those are
different quantities. A hand-computed fixture proves the
maximum-destination-backlog ranking CAN change under the corrected
definition (one spiked model vs one steady model rank in opposite
orders under the two definitions). Whether the thesis
maximum-backlog ranking changes cannot be determined without the
thesis daily records, which are unavailable. Corrected outputs must
not be presented as reproducing the thesis values.

**Shipment totals** are a throughput measure: the simulator's
shipment log records transfers across multiple legs of the network.
Total recorded shipment units are NOT customer demand fulfilled, and
fewer shipments are NOT automatically better inventory performance.

### 5.2 Ranking direction

Ranks are **direction-oriented ranks computed from values** (never
hardcoded). "Best rank" means best under the stated numerical
direction, not a desirability judgement.

- Forecast metrics (MAE, RMSE, MASE): **lower is better** (rank 1 =
  smallest value).
- Inventory metrics in the F03 framework (six primary):
  - `fill_rate`: **higher is better** (rank 1 = largest value).
  - `total_unfilled_demand`, `average_destination_inventory`,
    `average_total_network_inventory`,
    `average_destination_backlog`, `final_destination_backlog`:
    **lower is better** as a numerical direction.
- Inventory metrics are **operational outcomes, not a universal
  desirability scale**. Higher fill rate and lower unfilled demand
  have clear preferred directions, but lower inventory is not
  automatically better without an explicit cost or service objective.
  No composite inventory score, no summed ranks, no single overall
  winner may be constructed. Maximum inventories and total shipment
  units are reported as quantities; when ranked (runner's 10-metric
  set), they use the lower-is-better numerical direction, with the
  same desirability caveat.

## 6. Ties, rank differences, agreement, correlations

- **Ties:** average tie method (`rank(method="average")`), matching
  the runner. (The notebook locked table used `rank(method="min")`;
  the difference is documented as F11 and must not be silently mixed.)
- **Rank difference:** Δ = inventory rank − forecast rank, per model,
  per (horizon, scenario, forecast metric, inventory metric).
- **Model-level exact agreement:** share of model rows with Δ = 0.
- **Complete-ordering agreement:** share of combinations where the
  full three-model forecast rank vector equals the full inventory
  rank vector. These two estimands must never be conflated.
- **Horizon/scenario breakdowns:** horizon-level and scenario-level
  mean absolute rank differences are rebuilt from the SAME
  underlying alignment table, with exact denominators (model-row
  counts) recorded. Each breakdown's denominator-weighted mean must
  reproduce the overall mean absolute rank difference; a mismatch
  is an error.
- **Spearman rho / Kendall tau-b:** descriptive only. With three
  models, Spearman rho can only take values in {−1, −0.5, 0, 0.5, 1}
  when there are no ties; a single rank swap changes rho by 0.5.
  Kendall tau-b is equally coarse.

## 7. Three-model limitation

- With only three forecasting models, rank correlations are
  **descriptive, not strong inferential evidence**. No p-values,
  confidence intervals, or standard errors are computed.
- The 288 framework combinations (4 horizons × 4 scenarios × 3
  forecast metrics × 6 primary inventory metrics) are **repeated
  descriptive comparisons, not 288 independent observations**. No
  pooled inferential statistics implying independence may be
  calculated.

## 8. Fill-rate / unfilled-demand redundancy

- When demand is fixed and the evaluation window is identical, fill
  rate and total unfilled demand produce **identical rank orderings**
  by construction (fill = 1 − unfilled/demand, demand constant
  across models). The six primary inventory metrics therefore carry
  **five distinct inventory dimensions, not six**. The primary
  analysis retains both; the sensitivity analysis excludes one
  (`total_unfilled_demand`) and is labelled as sensitivity.

## 9. Synthetic scope of F03/F04 tests

- **F03 tests** are synthetic fixtures that test the alignment
  script's code logic (validation, ranking, agreement, sensitivity).
  They do not verify any thesis result.
- **F04 test** runs the **real simulator** with the **verbatim
  thesis injection methods**, but on synthetic inputs (31 days,
  3 blocks, normal scenario, no outages). Equivalence is empirically
  demonstrated for those tested conditions; it is not a verification
  of the thesis's 7300-day runs, which were not rerun.
- **Passing code tests ≠ verifying thesis results.** Thesis results
  are verified only by recomputation from real frozen outputs
  (F01/F05 scripts on real data), which is BLOCKED (see §10).

## 10. Unresolved data, execution, and provenance issues

1. **F01 real-data execution BLOCKED.** 52 frozen files on
   `D:\ISOMORPH\thesis_frozen\` are inaccessible from this machine
   (no D:\ mount): 48 inventory files (4 scenarios × 3 models ×
   daily/inventory/backlog/shipments) + 4 frozen-demand files.
   Exact paths in `STAGE1_CLOSEOUT_REPORT.md`.
2. **F05 real-data execution BLOCKED.** Forecast files + frozen
   demand (above) inaccessible. Normal's forecast file
   (`forecast_results\normal\test_forecasts.csv`) has **unresolved
   provenance**: no cell in the notebook writes it; cell 91 searches
   for it. It must not be treated as notebook-verified output.
3. **F03 never run on real outputs.** No runner outputs exist in the
   repository; the 7300-day MASTER CSVs are on D:\. The 7300-day
   adapter is tested synthetically against the documented notebook
   schemas only.
4. **Runner never executed.** Schema verified from source only.
5. **5000-day inventory duplication (F06).** The supplied
   `Inventory_Outcomes_5000.csv` is numerically identical to the
   3000-day file (all 132 numeric cells). No independent 5000-day
   inventory horizon is demonstrated by those supplied files.
6. **Cells 77/89 incomplete saved outputs (F07).** Normal full
   inventory output ends at Day 2045/7300; Supply forecast output
   ends at item 43/50. Completion is not demonstrated by saved
   outputs. Locked Supply forecast values are therefore untraceable
   from saved notebook output.
7. **Slide MASE provenance (F05).** Locked Demand/Combined MASE
   values come from presentation slides, not a notebook computation;
   the definition behind the slide values is unknown. Do not
   substitute a definition merely to match a reported number.
8. **F01 inventory-level definition.** The recomputation uses
   end-of-day snapshots (`inventory_history`, `backlog_history`)
   for levels, with daily-aggregate definitions (v2) matching the
   notebook's groupby-day-sum aggregation. The notebook cells may
   have used before-ship columns (`dest_on_hand_end_before_ship`,
   `dest_backlog_end_before_ship`) for some metrics. This
   definitional difference must be reconciled when (not before)
   recomputed values are compared to locked values.
9. **Combined provenance.** Cell 109's locked table is hardcoded and
   does not read cell 106's outputs; the match to cell 106 is
   supported but not proven (transcription). Cell 106's Combined
   inventory used the full horizon (F01); its test-window values do
   not exist until F01 recomputation runs on real data.
10. **Supply LightGBM protocol.** Cell 89 uses per-block refitting
    and zero-capping; the Normal final method trains once without
    capping. This is an interpretation caveat for Supply LightGBM,
    not a blocker for F05 recomputation (which recomputes from the
    saved forecasts as-is).
11. **LightGBM subsampling (runner).** The runner's `subsample=0.8`
    is inert (LightGBM disables bagging when `subsample_freq`
    defaults to 0); `colsample_bytree=0.8` is active feature
    subsampling. The notebook's LightGBM sets neither. Documented
    protocol difference; do not "fix" by enabling bagging.
12. **Maximum-backlog ranking sensitivity.** The corrected daily
    aggregate maximum backlog can rank models differently from the
    old single-record maximum (proven by fixture). Whether the
    thesis maximum-backlog ranking changes is undecidable without
    the thesis daily records.
