# Validation and known-limitations report

Status of the checks I ran and what's still open.
Every status below cites what was actually checked.

**Two kinds of checking, kept separate.** No thesis result has
been recomputed from the original experimental records
(forecast files, inventory histories, runner outputs),
because those records are not in this repository. What has
been done: (a) code logic tested on synthetic fixtures,
(b) code inspection against the notebook and simulator
source, (c) consistency checks calculated from values
printed in the thesis (appendix tables, locked table),
(d) direct comparison of supplied files, and (e) one test
on the real simulator under synthetic conditions (F04).
Printed-value checks compare the thesis's printed tables
against each other; they do not reproduce the experiment.

The F01/F05 real-data runs are blocked (see
`docs/data_manifest.md`).

## What the F-numbers mean

F01 to F07 are finding numbers from the checks of this repo
against the thesis, the notebook, and the simulator. They are
just labels so the docs can refer to each finding without
re-explaining it.

- F01 to F05 have code behind them: F01, F03, and F05 are
  scripts in `scripts/`, F02 is a set of definitions in
  `docs/methodology.md`, and F04 is a test in `tests/`. Each
  has a section below with status, evidence, and what is
  still open. F05 is covered in more detail in
  `docs/discrepancy_report.md`.
- F06 and F07 are recorded limitations, not fixes: the
  duplicated 5,000-day files (F06) and the incomplete
  notebook outputs (F07). Nothing in the repo can fix them
  until the original files are available. F06 is covered in
  full in `docs/reproducibility_and_validation.md` §1; F07
  appears as a row in the table below.

## F01 - Common evaluation window for inventory metrics

- **Status: confirmed; correction implemented; real-data verification blocked.**
- **Evidence:** Notebook cell 106 aggregates Combined inventory over
  the full horizon (unfiltered records), while cells 78, 87, 91
  filter Normal, Demand, Supply to test days 6200–7299. Combined's
  locked fill rate (0.138485) matches full-horizon arithmetic;
  the other scenarios' locked fill rates match test-window arithmetic.
- **Correction:** `scripts/recompute_inventory_windows.py` recomputes
  all scenarios/models over one common test window (default
  6200–7299) with identical definitions, validates sortedness,
  duplicates, coverage, item sets, demand↔inventory consistency,
  verifies the fill-rate identity, and keeps
  `full_horizon_demand` separately labelled. Inventory/backlog
  levels use **daily aggregates** (aggregation version
  `inventory-metrics-v2-daily-aggregate`: sum across items/nodes per
  day, then mean/max across test days), matching the notebook's
  groupby-day-sum aggregation. 14 synthetic tests pass, including
  hand-computed values, duplicate/gap/unsorted/mismatch
  rejection, a multi-digit-day sorting check, and a demonstration that the
  maximum-backlog ranking can change under the corrected
  definition.
- **Remaining:** run on the 48 frozen inventory files + 4 frozen
  demand files (blocked; exact paths in `docs/data_manifest.md`).

## F02 - Full-run vs test-window demand; fill-rate identity

- **Status: confirmed; definitions documented; real-data verification blocked.**
- **Evidence:** Locked `total_demand` is full-horizon for all
  scenarios (Normal/Supply 75,262,671; Demand/Combined 101,932,845)
  while most other locked inventory metrics are test-window.
  The identity was verified against the simulator: `step()` stage 4
  guarantees `served + unfilled = demand` per (day, item), so
  `fill_rate = 1 − total_unfilled / total_demand` holds only when
  both quantities share the window and population.
- **Correction:** `docs/methodology.md` §1–2, §4 states the window
  rule, the separation of full-horizon totals, and the identity with
  its conditions. The F01 script verifies the identity per
  scenario/model and fails explicitly if it breaks. The runner now
  also writes the auditable totals (`total_test_demand`,
  `total_served_from_stock`, `total_unfilled_demand`) in every
  inventory record and validates the identities
  (`served + unfilled = test demand`,
  `fill_rate = served / test demand`) plus a common frozen
  test-demand total across the three models in each
  horizon/scenario before saving aggregate results.
- **Remaining:** the identity check runs only when F01 runs on real
  data (blocked).

## F03 - Forecast-to-inventory ranking alignment

- **Status: confirmed gap; implementation complete; real-data execution blocked.**
- **Evidence:** The runner writes forecast metrics and inventory
  rankings separately; notebook cell 109 produces both rank sets
  but never compares them. No alignment computation existed in the
  repository.
- **Correction:** `scripts/alignment_analysis.py` joins forecast and
  inventory ranks on (horizon, scenario, model), recomputes ranks
  from values (average tie method), validates item sets, models,
  complete daily coverage, common test window, experiment grid, and
  finite values, and reports Δ, |Δ|, **model-level exact agreement**
  (share of model rows with Δ = 0) and **complete-ordering
  agreement** (share of combinations where the full three-model
  vectors match), plus descriptive Spearman/Kendall. No p-values,
  CIs, or composite scores. The primary analysis uses mean-of-item
  forecast ranks; a separate, labelled sensitivity uses
  median-of-item forecast ranks. Horizon-level and scenario-level
  mean absolute rank differences are rebuilt from the same
  alignment table with exact denominators recorded, and each
  breakdown's denominator-weighted mean must reproduce the overall
  mean. 48 synthetic tests pass, including adversarial cases
  (missing interior day, duplicate rows, differing windows across
  models, grid gaps), finite-value rejection, a median-sensitivity
  fixture with hand-computed orderings, a breakdown-consistency
  fixture, and a non-vacuity check (the adversarial tests fail on
  the pre-fix version).
- **Remaining:** run on real runner outputs (none exist in the
  repository) or adapted 7,300-day outputs. The 288 combinations are
  repeated descriptive comparisons, not independent observations.

## F04 - EMA injection equivalence (compensation vs hold)

- **Status: confirmed difference in method; equivalence empirically demonstrated for tested conditions.**
- **Evidence:** The runner and notebook Normal/Demand use
  *compensation* (pre-update EMA set so the native update lands on
  `forecast_sum / 7`, α stays 0.05). Notebook Supply/Combined use
  *hold* (`demand_ema = target / 7`, α set to 0.0). Verified by
  reading the simulator: EMA is updated in `step()` stage 4 and read
  only in stage 5 (after the update); α is read only at the update;
  neither injection consumes RNG.
- **Test:** `tests/test_ema_equivalence.py` runs the **real v2
  simulator** with the verbatim thesis injection wrappers, identical
  synthetic inputs, 31 days (10 warm-up + 21 test = 3 blocks), all 50
  items, normal scenario, no outages. Post-update EMA equal within
  1e-9; daily records, shipments, and inventory/backlog/in-transit
  histories exactly identical. Sensitivity shown: wrong-stage and
  wrong-coefficient (0.10 vs 0.05) variants diverge. 7 tests pass.
  Simulator files integrity-checked by SHA-256.
- **Remaining:** none for the equivalence claim under the tested
  conditions. The thesis's 7,300-day runs were not rerun (not
  needed for this claim). Hold remains the more fragile method
  (it mutates global α); compensation is the recommended single
  documented method.

## F05 - Consistent MASE definition and aggregation

- **Status: confirmed inconsistency; correction implemented; real-data verification blocked.**
- **Evidence:** Locked Normal forecast values match notebook cell 67
  (mean-of-item). Locked Demand MAE matches cell 81 but RMSE is
  pooled and MASE comes from presentation slides (definition
  unknown). Locked Combined MASE matches neither cell 110
  (test-scale diagnostic) nor cell 112 (training-scale). Locked
  Supply values are untraceable from saved output (cell 89
  truncated at item 43/50). Cross-check: Supply demand equals Normal
  demand, so Seasonal Naïve forecasts must be identical; locked MAE
  matches but RMSE/MASE differ. This shows the locked RMSE/MASE
  values are inconsistent with the locked MAE if all three were
  computed from the same forecast set. Possible explanations
  include different aggregation, different source files for
  different metrics, or transcription differences; the available
  records do not distinguish between these.
- **Correction:** `scripts/recompute_forecast_metrics.py` uses one
  definition - per-item MAE/RMSE over the test window, per-item MASE
  with the item's training-period 7-lag scale, mean across items,
  never pooled - validates item sets, coverage, duplicates,
  forecast/actual alignment, training completeness, MASE
  denominators, and finite values, and includes the 7300-day
  adapter (notebook `notebook_per_row` + `notebook_demand` formats,
  tested synthetically against the actual notebook schemas).
  Optional locked-values comparison produces match / differ /
  cannot-check. 17 synthetic tests pass, including a comparison showing that
  mean-of-item RMSE/MASE differ from pooled values and
  finite-value rejection.
- **MASE denominator check:** the runner's denominator uses
  pre-test history through `VALIDATION_END` (which includes the
  validation period); the F05 script uses days 0..`train_end`
  (0–6199 for the 7,300-day horizon, matching notebook cell 112).
  Both use the available pre-test training history with seasonal
  period 7, as documented in `docs/methodology.md` §3.
- **Remaining:** run on the frozen forecast + demand files (blocked;
  exact paths in `docs/data_manifest.md`). Normal's forecast file
  has unresolved provenance (no notebook cell writes it).
  `docs/discrepancy_report.md` records every locked/slide value as
  **cannot-check by recomputation** until then.

## LightGBM parameter check (runner)

- **Finding: `subsample=0.8` is inert; `colsample_bytree=0.8` is active.**
  Verified against LightGBM's parameter documentation:
  `bagging_fraction` (alias `subsample`) requires `bagging_freq`
  (alias `subsample_freq`) set to a non-zero value to enable
  bagging; `bagging_freq` defaults to 0 (bagging disabled). The
  runner does not set `subsample_freq`, so no row subsampling
  occurs. `colsample_bytree` (alias `feature_fraction`) = 0.8 is
  active: a random 80% subset of features is selected before
  training each tree. The 7,300-day notebook's LightGBM sets
  neither parameter (no feature subsampling, no bagging).
- **Action:** documented only (runner comment + protocol doc).
  `subsample_freq` was NOT set and no forecast setting was
  changed, because that would change the experiment. Any protocol
  with bagging enabled must be identified as a separate variant,
  never substituted into the historical one. LightGBM is not
  installed in this environment, so the effect was verified from
  the official parameter documentation, not by executing LightGBM.

## Runner inventory aggregation correction

- **Finding:** the runner computed inventory/backlog level metrics
  over individual (day, item) rows - per-row means and
  single-record maxima - while the 7,300-day notebook computes
  daily aggregates (groupby day, sum, then mean/max; verified in
  notebook cells 78, 87, 91, 106). The definitions were not
  consistently aligned.
- **Correction:** `compute_inventory_metrics()` in the runner now
  uses daily aggregates (aggregation version
  `inventory-metrics-v2-daily-aggregate`), with exact coverage
  validation, per-row and aggregate identity checks, and
  frozen-demand consistency. The F01 script was corrected to the
  same definitions. The runner also writes a run manifest
  (`run_manifest.json`), refuses a non-empty output directory
  without `--overwrite`, and validates forecast coverage and the
  output schema before saving aggregate results. 18 new runner
  tests pass (hand-computed aggregates, identity/coverage/finite
  checks, manifest, overwrite, pre-save validation).
- **Ranking effect:** a hand-computed fixture shows the
  maximum-destination-backlog ranking CAN change under the
  corrected definition (spiked vs steady backlog profiles rank in
  opposite orders). Whether the thesis ranking changes cannot be
  determined without the thesis daily records (unavailable).
  Corrected runner outputs must not be presented as reproducing
  the thesis values.

## Other reproducibility problems (checked)

| Issue | Status |
|---|---|
| Duplicated 5,000-/3,000-day inventory outputs (F06) | **Confirmed** by direct comparison (byte-identical). No independent 5,000-day inventory evidence in the supplied files. Unresolved. |
| Supply LightGBM protocol differs (refit + zero-clip, cell 89) vs Normal train-once, no clip (cell 67) and runner train-once, no clip | **Confirmed** from notebook/runner code. Interpretation caveat, not silently reconciled. Unresolved as a protocol question. |
| Notebook cells 77/89 incomplete saved outputs (F07) | **Confirmed** (cell 77 ends Day 2045/7300; cell 89 ends item 43/50). Completion not demonstrated by saved outputs. |
| Tie handling differs (runner `average` vs notebook cell 109 `min`) | **Confirmed.** F03 uses `average`, matching the runner; documented in `docs/methodology.md`. |
| Runner ranks 10 inventory metrics; locked table ranks 6 | **Fixed.** The runner now ranks the same 6 primary metrics; the wider set is descriptive. |
| Requirements unpinned; no lock file; README Python 3.9+ vs notebook Python 3.12.13 | **Confirmed.** Documented in README setup section. Unresolved (no lock file; versions not reconstructed). |
| Notebook `D:\ISOMORPH\...` paths; `!pip install` cells | **Confirmed.** Notebook is not clean-room executable. Documented; paths in this repo's user-facing docs are configurable placeholders, except provenance references to original file locations. |
| Single seed (2025), single realization; 50 SKUs share one network | **Confirmed.** Stated as a limitation in README + methodology. |
| No PNG/CSV/HTML result artifacts in the repository | **Confirmed.** By design: raw outputs are excluded via `.gitignore`; the manifest lists what is missing. |
| Locked table (cell 109) hardcoded, no file reads | **Confirmed.** Transcription from cell 106 supported but not proven; MASE source unresolved. Do not alter locked values without evidence and a documented reason. |
| No LICENSE file | **Confirmed.** Not added: simulator provenance, ownership, and redistribution permission have not been established. |
| Secret / private-material scan | **Clean on the scanned scope.** Pattern scan of the working copy found no credentials, tokens, private keys, or email addresses (only a `.gitignore` section header and non-secret digit strings). **Limitations:** the remote repository's commit history was NOT inspected; a pattern scan cannot prove no secret was ever committed. Check the remote history separately before public release. |

## What has actually been verified (evidence)

1. F04 equivalence on the real simulator under matched synthetic
   inputs (see F04 above).
2. F01/F03/F05 code logic on synthetic fixtures (109 tests total
   in this package: 48 F03 + 7 F04 + 14 F01 + 17 F05 + 18 runner),
   including adversarial validation and hand-computed values.
3. Runner aggregation/validation/manifest/overwrite logic on
   hand-computed fixtures (18 tests); the runner itself has not
   been executed end to end.
4. Simulator file integrity (SHA-256) for the F04 test.
5. 5,000-/3,000-day inventory-file duplication by direct comparison.
6. Notebook aggregation convention (groupby day, sum, then
   mean/max) by reading cells 78, 87, 91, 106.
7. LightGBM subsampling semantics from the official parameter
   documentation (bagging requires `bagging_freq > 0`).
8. All F01–F05 path/schema claims above by reading the notebook,
   runner, and simulator source (not by executing them).
9. `py_compile` syntax checks for the three root `.py` files
   (syntax only - not executability or correctness).
10. Printed-value consistency checks: Table 4.2 recomputed from
    Appendix B.4 values (7,300 days); B.8 printed ranks compared
    against B.4-based orderings; Table 4.1 orderings compared
    against Appendix A values. These check the printed tables
    against each other; they do not reproduce the experiment.

## What remains unverified and why

- **Every numerical thesis result** (forecast metrics, inventory
  outcomes, alignment shares) - none has been recomputed from
  the original experimental records; the frozen files are
  inaccessible.
- **The runner** has never been executed end to end in a clean
  environment here.
- **The notebook** has never been re-executed in a clean
  environment; saved outputs are preserved as-is.
- **Locked-table values** - transcription, MASE definition, and
  aggregation provenance unresolved (see F05).
- **5,000-day inventory evidence** - duplicated files (see F06).
- **Normal forecast file provenance** - no notebook writer.

## Recomputation commands (when the frozen files are accessible)

From the repository root:

```bash
# Runner (writes run_manifest.json; refuses a non-empty output dir
# without --overwrite; validates coverage/schema before saving)
python thesis_short_horizon_experiments.py \
  --output-dir thesis_short_runs --horizons 2000 --scenarios normal

# F03 alignment on runner outputs (writes alignment_results.csv,
# alignment_results_median_forecast_ranks.csv, alignment_summary.json)
python scripts/alignment_analysis.py \
  --forecast-item-metrics thesis_short_runs/all_forecast_item_metrics.csv \
  --forecasts thesis_short_runs/all_test_forecasts.csv \
  --inventory-outcomes thesis_short_runs/all_inventory_outcomes.csv \
  --output-dir thesis_short_runs/alignment
```

From `scripts/` (see `docs/data_manifest.md` for the exact files):

```bash
# F01 (manifest JSON per the script docstring; one run, all scenarios)
python -m recompute_inventory_windows --manifest manifest.json \
  --output-dir <OUT>/f01 --test-start 6200 --test-end 7299

# F05, one run per scenario (7300-day: train-end 6199, test 6200-7299)
# Demand: three per-model files, format notebook_demand
python -m recompute_forecast_metrics \
  --forecast-file <COPY>/forecast_results/demand_disruption/seasonal_naive_test.csv --forecast-format notebook_demand \
  --forecast-file <COPY>/forecast_results/demand_disruption/ets_test.csv --forecast-format notebook_demand \
  --forecast-file <COPY>/forecast_results/demand_disruption/lightgbm_test.csv --forecast-format notebook_demand \
  --demand-file <COPY>/demand_disruption/daily_records.csv \
  --scenario demand_disruption --train-end 6199 --test-start 6200 --test-end 7299 \
  --output-dir <OUT>/f05/demand_disruption

# Supply / Combined / Normal: one file, format notebook_per_row
python -m recompute_forecast_metrics \
  --forecast-file <COPY>/forecast_results/supply_disruption/test_forecasts.csv --forecast-format notebook_per_row \
  --demand-file <COPY>/supply_disruption/daily_records.csv \
  --scenario supply_disruption --train-end 6199 --test-start 6200 --test-end 7299 \
  --output-dir <OUT>/f05/supply_disruption
# (Combined: substitute combined_disruption paths; Normal: substitute
# normal paths - Normal's file provenance remains unresolved.)
```

Add `--locked-values <locked.csv>` (columns: scenario, model, MAE,
RMSE, MASE, source; transcribed from notebook cell 109) to an F05
run to produce `discrepancy_report.csv`.

## Cross-checks against the thesis

I checked the thesis against this repo claim by claim. The full
mapping, with method, source, and uncertainty for each check, is
in `docs/thesis_traceability_matrix.md` (§9, §11). The findings
that change the validation picture, in brief:

- **Table 4.2 alignment values match a 456-framework
  recomputation, not the 288 framework.** From Appendix B.4
  values: 456 + min ties gives the thesis's 7,300-day
  0.990 / 32.3% (285/288, 93/288). The repo's F03 (288 +
  average ties) gives 0.9722 / 34.72% from the same values -
  it implements the thesis's stated 6-metric procedure, not
  the framework the Table 4.2 numbers are consistent with.
  The thesis does not state which framework Table 4.2 uses;
  the 456 attribution is inferred from the numbers. Full
  detail: matrix §9.3.
- **Appendix B.8 vs B.4: eight cells differ** at 7,300 days
  (a ninth, Normal fill, is consistent with B.4 rounding).
  The network-inventory row differs from the B.4-based
  ordering for Demand, Supply, and Combined. The printed
  tables alone do not establish which table is in error.
  Full detail, with the cell-by-cell comparison:
  matrix §9.5.
- **Appendix A.4 vs locked table (Supply):** A.4 sets Supply
  forecast values equal to Normal; the locked table has
  distinct Supply values. Unresolved; the available records
  do not establish which source is correct. Matrix §6.8,
  §11.4.
- **Appendix B.3 (5,000-day) inventory matches B.2
  (3,000-day).** The thesis does not state this. Method,
  source, and uncertainty: `docs/reproducibility_and_validation.md`
  §1.
- **Appendix B.4 / Table 4.3 Combined values are
  full-horizon;** other scenarios are test-window. The
  thesis does not note the difference. Matrix §5.4, §11.6.
- **Differing statements recorded:** exact-agreement
  definition (§4.5/C.3 model-level vs C.1 complete-ordering);
  456 vs 288 framework (abstract vs C.1); Table 3.5
  directions for all ten metrics vs §4.4 (four descriptive
  measures not ranked); EMA procedure (thesis describes
  compensation only; code also uses hold for
  Supply/Combined). Matrix §11.
- **Thesis-silent items:** split boundaries
  (implementation-defined); tie method (repo uses average;
  the Table 4.2 numbers are consistent with min); ISOMORPH
  version (not recorded anywhere).
- **Provenance:** the thesis's shorter-horizon experiments
  were dashboard-generated; the repo's runner is a
  reimplementation, not the original dashboard code.
- **No thesis result has been recomputed from original
  records** (none are in the repo). The checks above were
  calculated from values printed in the thesis.
