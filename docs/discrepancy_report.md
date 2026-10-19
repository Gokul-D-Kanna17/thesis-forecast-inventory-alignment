# F05 discrepancy report - locked-table / slide values vs recomputed metrics

**Status: BLOCKED - no recomputed values exist.**

Real-data recomputation is blocked because the required forecast and
frozen-demand files are on `D:\ISOMORPH\thesis_frozen\` and are not
accessible from this machine (no D:\ mount). Until the F05 script runs
on real data, **every locked/slide value is "cannot-check" by
recomputation**. Nothing in this file is a recomputation result.

When real data is available, `scripts/recompute_forecast_metrics.py
--locked-values <csv>` produces `discrepancy_report.csv` with per
(scenario, model, metric) status **match / differ / cannot-check**
(tolerance: |diff| ≤ 1e-6 + 1e-6·|locked|), with signed differences
for differ rows. The script's discrepancy logic is tested synthetically
(`tests/test_recompute_forecast_metrics.py::test_discrepancy_report`).

## Prior trace (NOT a recomputation)

The table below is the earlier trace from reading the notebook and
runner code. It is **not** a recomputation and must
not be cited as one. It records which locked values are traceable to
a notebook computation, which are mixed-aggregation, and which are
untraceable.

| Scenario | Metric | Locked value | Traceable to | Status (prior trace) |
|---|---|---|---|---|
| Normal | MAE / RMSE / MASE | cell 67 values | Cell 67 (mean-of-item) | matches cell 67 |
| Demand | MAE | cell 81 values | Cell 81 (mean-of-item) | matches cell 81 |
| Demand | RMSE | pooled values | Pooled (not cell 81) | differs from cell 81 (aggregation) |
| Demand | MASE | slide values | Presentation slides | provenance unknown |
| Combined | MAE / RMSE / MASE | = locked Demand | Same demand as Demand | same as Demand by design |
| Combined | MASE (alt) | cell 110: test-scale | Cell 110 diagnostic (test actuals scale) | differs from locked |
| Combined | MASE (alt) | cell 112: training-scale | Cell 112 (training scale) | differs from locked |
| Supply | MAE / RMSE / MASE | locked values | No complete saved output (cell 89 truncated, F07) | cannot-check from saved outputs |

Key cross-check (prior trace, not recomputation): Supply demand equals
Normal demand, so Seasonal Naïve forecasts must be identical; locked
MAE matches (17.382436 vs 17.3824) but locked RMSE/MASE differ
(Normal 22.0150 / 1.0363 vs Supply 22.368811 / 0.999848). This shows
the locked RMSE/MASE values are inconsistent with the locked MAE if
all three were computed from the same forecast set. Possible
explanations include different aggregation, different source files
for different metrics, or transcription differences; the available
records do not distinguish between these.

## Files blocking recomputation

- `D:\ISOMORPH\thesis_frozen\forecast_results\demand_disruption\{seasonal_naive_test,ets_test,lightgbm_test}.csv`
  (columns: item, day, forecast, actual; model from filename)
- `D:\ISOMORPH\thesis_frozen\forecast_results\supply_disruption\test_forecasts.csv`
  (columns: item, model, split, day, actual, forecast)
- `D:\ISOMORPH\thesis_frozen\forecast_results\combined_disruption\test_forecasts.csv`
  (same schema; written by cell 105)
- `D:\ISOMORPH\thesis_frozen\forecast_results\normal\test_forecasts.csv`
  (**provenance unresolved**: no notebook cell writes it; cell 91 searches for it)
- `D:\ISOMORPH\thesis_frozen\{normal,demand_disruption,supply_disruption,combined_disruption}\daily_records.csv`
  (frozen demand: training series for the MASE denominator + actuals cross-check)

The locked values themselves (for the `--locked-values` input) are in
notebook cell 109 (hardcoded). I still need to transcribe them into
a CSV; they are not hardcoded in the script.
