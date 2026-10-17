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
- **LightGBM:** nine features — `lag_1`, `lag_7`, `lag_14`, `lag_28`, `rolling_mean_7`, `rolling_mean_28`, `rolling_std_28`, `day_of_week`, `week_of_year` — with `n_estimators=300`, `learning_rate=0.05`, `num_leaves=31`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=2025`. The runner fits one model per item on pre-test history and predicts recursively within each 7-day block.
- **Forecast horizon:** 7 days, evaluated over rolling forecast blocks in the test window.
- **Forecast measures:** MAE, RMSE and MASE. These are reported at item and aggregate levels in the code; lower values indicate smaller forecast errors. MASE uses the denominator `mean(|train[7:] - train[:-7]|)` over pre-test history through `VALIDATION_END` (see `forecast_metrics` in the runner).

The runner seeds Python and NumPy with `2025`. The simulator receives this seed when each demand and inventory run is constructed. A fixed seed alone does not guarantee identical outputs across software versions or a different runtime environment.

## Operating scenarios

- `normal`
- `demand_disruption`
- `supply_disruption`
- `combined_disruption`

Within a given short-horizon scenario and run length, demand is generated once and stored as a frozen demand matrix. Forecast models and the corresponding inventory comparisons use that same realized demand series.

## Inventory outcomes and ranking directions

The runner writes fill rate; total unfilled demand; average and maximum destination inventory; average total network inventory; maximum total network inventory; average, maximum and final destination backlog; and shipment units over the test window.

The code ranks lower values as better for most listed inventory metrics and higher values as better for fill rate. This includes some measures that the thesis treats as descriptive rather than primary decision objectives, such as total shipment units. These runner-generated ranks should not automatically be treated as the thesis's primary alignment set. The primary analysis uses six operational measures; see the root README and validation notes.

## Outputs from the runner

The script writes configuration JSON, frozen demand, per-model test forecasts, item-level and aggregate forecast metrics, test-window simulation records, inventory outcomes and an inventory-metric ranking table. By design, these outputs are retained separately.

**The current runner does not generate a joined table comparing forecast ranks with inventory ranks.** Therefore, running it successfully is not sufficient to reproduce the thesis's central alignment analysis.

## Relationship to the 7,300-day notebook

The primary notebook defines a 7,300-day experiment with training days 0–5,099, validation days 5,100–6,199 and test days 6,200–7,299. The short-horizon runner and notebook were implemented through different workflows. In particular, the 7,300-day Supply Disruption LightGBM implementation (notebook cell 89) refits at each 7-day forecast origin and caps each recursive prediction at zero via `max(0.0, pred)`; the shorter-horizon runner fits one LightGBM model per item on pre-test history and predicts recursively within each 7-day block without that cap. The 7,300-day Normal LightGBM cells fit once per item and do not cap predictions. Cross-horizon results must retain this qualification.

The 2,000-, 3,000-, 5,000- and 7,300-day configurations are not four independent statistical replications. They are distinct simulation configurations used to study sensitivity to the specified horizon and workflow.

## Execution record to retain

For any new run intended for analytical use, record the command, run date, Python version, installed dependency versions, selected horizons and scenarios, process completion status, output directory and any data/validation warnings. Do not report output files as validated merely because they exist.
