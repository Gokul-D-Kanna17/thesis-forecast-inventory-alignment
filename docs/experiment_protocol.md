# Experiment protocol

This document describes the short-horizon runner as it is implemented in `thesis_short_horizon_experiments.py`. It is not a substitute for examining the code, and it does not establish that a run has completed successfully.

## Horizons and temporal windows

Day indices are zero-based and the endpoints below are inclusive.

| Run length | Initial training window | Validation window | Test window | Forecast horizon |
|---:|---|---|---|---:|
| 2,000 days | 0–999 | 1,000–1,499 | 1,500–1,999 | 7 days |
| 3,000 days | 0–1,499 | 1,500–2,249 | 2,250–2,999 | 7 days |
| 5,000 days | 0–2,999 | 3,000–3,999 | 4,000–4,999 | 7 days |

The runner's final model fitting uses pre-test observations through `VALIDATION_END`; the validation period is therefore part of the available pre-test history for final forecasts. The current code does not implement a separate hyperparameter-selection pipeline based on the validation set. Read `fit_and_forecast` and `forecast_metrics` before describing the split as a conventional train/tune/test procedure.

## Forecasting methods and evaluation

- **Seasonal Naïve:** uses the value from the same weekday in the preceding week.
- **ETS:** level-only statsmodels `ExponentialSmoothing` (`trend=None`, `seasonal=None`), refit at each weekly forecast origin on the expanding history of observed demand.
- **LightGBM:** nine features - `lag_1`, `lag_7`, `lag_14`, `lag_28`, `rolling_mean_7`, `rolling_mean_28`, `rolling_std_28`, `day_of_week`, `week_of_year` - with `n_estimators=300`, `learning_rate=0.05`, `num_leaves=31`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=2025`. The runner fits one model per item on pre-test history and predicts recursively within each 7-day block.
  - **Subsampling check (verified against LightGBM's parameter documentation):** `subsample` (= `bagging_fraction`) = 0.8 is **inert** because `subsample_freq` (= `bagging_freq`) is unset and defaults to 0, and LightGBM disables bagging when `bagging_freq == 0` ("to enable bagging, `bagging_freq` should be set to a non zero value as well"). No row subsampling occurs. `colsample_bytree` (= `feature_fraction`) = 0.8 **is active**: a random 80% subset of features is selected before training each tree. Do NOT "fix" this by setting `subsample_freq` - that would change the experiment. Any protocol with bagging enabled must be identified as a separate variant. The 7,300-day notebook's LightGBM sets neither parameter (no feature subsampling, no bagging), so the runner and notebook differ in LightGBM feature subsampling (0.8 vs 1.0) - a documented protocol difference.
- **Forecast horizon:** 7 days, evaluated over rolling forecast blocks in the test window.
- **Forecast measures:** MAE, RMSE and MASE. These are reported at item and aggregate levels in the code; lower values indicate smaller forecast errors. MASE uses the denominator `mean(|train[7:] - train[:-7]|)` over pre-test history through `VALIDATION_END` (see `forecast_metrics` in the runner). If that denominator is zero (an exactly 7-periodic training series), MASE is undefined: the runner records NaN for that item and prints an explicit warning rather than substituting a pooled value or silently dropping the item. The F03 alignment script rejects non-finite values.

The runner seeds Python and NumPy with `2025`. The simulator receives this seed when each demand and inventory run is constructed. A fixed seed alone does not guarantee identical outputs across software versions or a different runtime environment.

## Operating scenarios

- `normal`
- `demand_disruption`
- `supply_disruption`
- `combined_disruption`

Within a given short-horizon scenario and run length, demand is generated once and stored as a frozen demand matrix. Forecast models and the corresponding inventory comparisons use that same realized demand series.

## Inventory outcomes and ranking directions

The runner writes fill rate; total unfilled demand; average and maximum destination inventory; average total network inventory; maximum total network inventory; average, maximum and final destination backlog; and shipment units over the test window. It also writes the auditable totals `total_test_demand`, `total_served_from_stock`, and `total_unfilled_demand`, the test-window start/end, and the metric-definition version (`aggregation_version = inventory-metrics-v2-daily-aggregate`).

**Aggregation (v2, corrected).** Destination inventory, destination backlog, and network inventory are DAILY AGGREGATES: each day's value is the sum across items (and across nodes for network inventory); the mean and maximum are taken across test days, and the final backlog is the last test day's aggregate. This matches the 7,300-day notebook's aggregation (groupby day, sum, then mean/max). Earlier versions of this runner used per-row (day, item) means and single-record maxima; those are different quantities. A hand-computed fixture shows the maximum-destination-backlog ranking can change under the corrected definition (see `tests/test_runner_inventory_metrics.py`); whether the thesis ranking changes cannot be determined without the thesis daily records. Corrected runner outputs must not be presented as reproducing the thesis values.

**Shipment totals.** The simulator's shipment log records transfers across multiple legs of the network. Total recorded shipment units are a throughput measure, NOT customer demand fulfilled, and fewer shipments are NOT automatically better inventory performance.

**Validation.** Before aggregate results are saved, the runner validates forecast day-coverage (exactly one row per (model, item, day) in the test window, no duplicates, finite values) and the inventory-outcome schema (required columns, finite values, the service identities `served + unfilled = test demand` and `fill_rate = served / test demand`, the aggregation version, and a common frozen test-demand total across the three models in each horizon/scenario). Missing, duplicated, or incomplete records fail explicitly rather than producing apparently valid summaries.

The code ranks only the six primary inventory metrics defined by the thesis (Section 4.4 / Appendix B): lower values as better for total unfilled demand, average destination inventory, average destination backlog, maximum destination backlog, and average total network inventory, and higher values as better for fill rate. The directions are defined once in `INVENTORY_RANK_DIRECTIONS` and applied by `rank_inventory_metrics()` (average tie method), with one test per metric verifying its direction (see `tests/test_runner_inventory_metrics.py`). Maximum destination inventory, maximum total network inventory, final destination backlog, and total shipment units are recorded as descriptive values and are NOT ranked, because the thesis assigns them no model ranking. These runner-generated ranks should not automatically be treated as the thesis's primary alignment set. The primary analysis uses six operational measures; see the root README and validation notes.

## Outputs from the runner

The script writes configuration JSON, a run manifest (`run_manifest.json`: seed, horizons/scenarios, split boundaries, model configuration, Python and dependency versions, date/time, output location, completion status), frozen demand, per-model test forecasts, item-level and aggregate forecast metrics, test-window simulation records, inventory outcomes and an inventory-metric ranking table. By design, these outputs are retained separately.

The runner refuses to use a non-empty output directory unless `--overwrite` is given, so a previous run cannot be silently overwritten.

**The current runner does not itself generate a joined table comparing forecast ranks with inventory ranks.** The separate F03 script (`scripts/alignment_analysis.py`) performs that joined analysis from the runner's outputs (and has not yet been run on real experiment outputs). It also cross-checks the item metrics file by recomputing item-level MAE/RMSE from the day-level forecast records and reporting mismatches as verification notes; MASE cannot be recomputed from day-level forecasts alone because it needs the training series (that recomputation is the F05 script's job). Therefore, running the runner successfully is not sufficient to reproduce the thesis's central alignment analysis.

## Relationship to the 7,300-day notebook

The primary notebook defines a 7,300-day experiment with training days 0–5,099, validation days 5,100–6,199 and test days 6,200–7,299. The short-horizon runner and notebook were implemented through different workflows. In particular, the 7,300-day Supply Disruption LightGBM implementation (notebook cell 89) refits at each 7-day forecast origin and caps each recursive prediction at zero via `max(0.0, pred)`; the shorter-horizon runner fits one LightGBM model per item on pre-test history and predicts recursively within each 7-day block without that cap. The 7,300-day Normal LightGBM cells fit once per item and do not cap predictions. Cross-horizon results must retain this qualification.

The 2,000-, 3,000-, 5,000- and 7,300-day configurations are not four independent statistical replications. They are distinct simulation configurations used to study sensitivity to the specified horizon and workflow.

## Execution record to retain

For any new run intended for analytical use, record the command, run date, Python version, installed dependency versions, selected horizons and scenarios, process completion status, output directory and any data/validation warnings. Do not report output files as validated merely because they exist.
