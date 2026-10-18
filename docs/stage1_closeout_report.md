# Stage 1 Closeout Report — Thesis Forecast-to-Inventory Alignment

**Scope:** staging only (`~/workspace/thesis-stage1/`). No original
notebook, repository, locked table, or source experiment output was
modified. Nothing committed or pushed. No full simulation rerun.

## 1. Implemented and tested (staging only)

| Item | Script | Tests | Result |
|---|---|---|---|
| F03 ranking-alignment analysis (v3) | `scripts/alignment_analysis.py` | `tests/test_alignment_analysis.py` (41) | Pass |
| F04 EMA equivalence | `tests/test_ema_equivalence.py` (7) | — | Pass |
| F01 inventory-window recomputation | `scripts/recompute_inventory_windows.py` | `tests/test_recompute_inventory_windows.py` (12) | Pass |
| F05 forecast-metric recomputation | `scripts/recompute_forecast_metrics.py` | `tests/test_recompute_forecast_metrics.py` (14) | Pass |
| F02/F05 methodology note | `docs/methodology_F02_F05.md` | — | Written |
| F05 discrepancy report | `docs/discrepancy_report.md` | — | BLOCKED status (see §3) |
| This report | `docs/STAGE1_CLOSEOUT_REPORT.md` | — | — |

**Actual test output (this run, full staged suite):**
`Ran 74 tests in 5.401s — OK`
(41 F03 + 7 F04 + 12 F01 + 14 F05. All synthetic fixtures except F04,
which runs the real simulator on synthetic inputs.)

**What each script does:**
- **F03** — joins forecast + inventory ranks on
  (horizon, scenario, model); recomputes ranks from values (average
  tie method); Δ, |Δ|, model-level exact agreement, complete-ordering
  agreement, descriptive Spearman/Kendall; validates item sets,
  models, complete daily coverage, common test window, experiment
  grid; sensitivity excluding one redundant metric. No p-values,
  CIs, SEs, or composite scores.
- **F04** — compensation vs hold on the real v2 simulator with
  verbatim thesis injection wrappers; identical synthetic inputs;
  31 days (10 warm-up + 21 test = 3 blocks), 50 items; EMA within
  1e-9, records/shipments/histories exactly identical; wrong-stage
  and wrong-coefficient variants diverge (sensitivity proven).
- **F01** — recomputes inventory outcomes over one common test
  window (default 6200–7299) from per-model records; validates
  sortedness, duplicates, coverage, item sets, demand-inventory
  consistency, optional forecast cross-check; verifies the fill-rate
  identity; keeps `full_horizon_demand` separately labelled.
- **F05** — recomputes per-item MAE/RMSE/MASE (training-period
  7-lag scale), mean across items, never pooled; validates item
  sets, coverage, duplicates, forecast/actual alignment, training
  completeness, MASE denominators; includes the 7300-day adapter
  (notebook `notebook_per_row` + `notebook_demand` formats) tested
  synthetically against the actual notebook schemas; optional
  locked-values discrepancy report (match / differ / cannot-check).

## 2. Executed successfully on actual thesis data

- **F04:** ran on the **actual simulator code** (v2 + base), with
  source files integrity-checked by SHA-256 against the audited
  values (base `604b62788548…`, v2 `12fe0cdc7a96…`). Inputs were
  synthetic. Equivalence is empirically demonstrated for the tested
  conditions (see F04 test docstring for scope).
- **Code reading (not execution):** the notebook
  (`thesis_7300day_notebook_organized_plain_text.ipynb`), the runner
  (`thesis_short_horizon_experiments.py`), and both simulator files
  were read to verify schemas, paths, injection code, and metric
  definitions. All F01/F05 input paths and schemas in this report
  come from that reading.
- **Nothing else** was executed on actual thesis data. No thesis
  result has been recomputed or verified.

## 3. Blocked by missing or inaccessible source files

The frozen files are on `D:\ISOMORPH\thesis_frozen\` (user's Windows
machine). This Linux VM has no D:\ mount (`/mnt`, `/media` absent;
`D:/ISOMORPH` inaccessible). The only CSVs accessible here are
already-aggregated summaries (e.g. `Forecast_Outcomes_*.csv`,
`Inventory_Outcomes_*.csv` in `~/workspace/user/files/`), which
**cannot** be used for recomputation (recomputing from aggregates
would be circular). Real-data execution is therefore BLOCKED.

**F01 — 52 files (48 inventory + 4 demand):**
- `thesis_frozen\inventory_results\normal\{seasonal_naive,ets,lightgbm}\{daily_records,inventory_history,backlog_history,shipments}.csv`
- `thesis_frozen\inventory_results\demand_disruption_full\{seasonal_naive,ets,lightgbm}\{...}.csv`
- `thesis_frozen\inventory_results\supply_disruption_full\{seasonal_naive,ets,lightgbm}\{...}.csv`
- `thesis_frozen\inventory_results\combined_disruption_full\{seasonal_naive,ets,lightgbm}\{...}.csv`
- `thesis_frozen\{normal,demand_disruption,supply_disruption,combined_disruption}\daily_records.csv`

**F05 — forecast files + the same 4 frozen-demand files:**
- `thesis_frozen\forecast_results\demand_disruption\{seasonal_naive_test,ets_test,lightgbm_test}.csv`
- `thesis_frozen\forecast_results\supply_disruption\test_forecasts.csv`
- `thesis_frozen\forecast_results\combined_disruption\test_forecasts.csv`
- `thesis_frozen\forecast_results\normal\test_forecasts.csv` — **provenance unresolved**: no notebook cell writes it; cell 91 searches for it.

**F03 — real outputs:** no runner outputs exist in the repository;
7300-day MASTER CSVs are on D:\. The runner was never executed.

**Unblocking:** copy the listed D:\ files (or grant access) and run
the F01/F05 CLIs with a manifest / file arguments pointing at the
copies. The scripts fail explicitly if any file is missing or
invalid; they do not fabricate. The Normal forecast file's writer
should be identified before its values are treated as
notebook-verified.

## 4. Remaining scientific limitations

- Three models only: rank correlations are descriptive, not
  inferential; no p-values/CIs/SEs.
- 288 combinations are repeated descriptive comparisons, not
  independent observations.
- One seed (2025), one realization per scenario; 50 SKUs share one
  network (not independent).
- Inventory metrics are operational outcomes, not a universal
  desirability scale; no composite score, no overall winner.
- F01 inventory levels use end-of-day snapshots; the notebook cells
  may have used before-ship columns — reconcile when comparing to
  locked values (see methodology note §10).
- 5000-day inventory duplication (F06) unresolved: supplied
  `Inventory_Outcomes_5000.csv` is identical to the 3000-day file.
- Cells 77/89 incomplete saved outputs (F07); locked Supply forecast
  values untraceable from saved output.
- Slide MASE provenance unknown; do not reconcile definitions to
  match reported numbers.
- Combined locked values are hardcoded (cell 109) and full-horizon
  (cell 106); test-window Combined values do not exist until F01
  runs on real data.
- F04 equivalence covers the tested synthetic conditions only;
  the 7300-day runs were not rerun.

## 5. Exact staged files changed in this closeout pass

New (this pass):
- `scripts/recompute_inventory_windows.py` (517 lines)
- `tests/test_recompute_inventory_windows.py` (310 lines)
- `scripts/recompute_forecast_metrics.py` (339 lines)
- `tests/test_recompute_forecast_metrics.py` (295 lines)
- `docs/methodology_F02_F05.md` (190 lines)
- `docs/discrepancy_report.md` (58 lines)
- `docs/STAGE1_CLOSEOUT_REPORT.md` (this file)

Pre-existing (frozen, verified this pass, not rewritten):
- `scripts/alignment_analysis.py` (828 lines), `tests/test_alignment_analysis.py` (935 lines)
- `tests/test_ema_equivalence.py` (405 lines)
- `README_STAGE1.md` (updated with closeout status), `alignment_diff_v1_v2.txt`, `alignment_diff_v2_v3.txt`, `v1/`, `v2/` backups

## 6. Source files used (read, never modified)

- `~/workspace/thesis-forecast-inventory-alignment-proposed/notebooks/thesis_7300day_notebook_organized_plain_text.ipynb`
- `~/workspace/thesis-forecast-inventory-alignment-proposed/Supplychaingeo_item50.py` (SHA-256 `604b62788548…`)
- `~/workspace/thesis-forecast-inventory-alignment-proposed/Supplychaingeo_item50_v2.py` (SHA-256 `12fe0cdc7a96…`)
- `~/workspace/thesis-forecast-inventory-alignment-proposed/thesis_short_horizon_experiments.py` (SHA-256 `deb4aed6ec7…`)
