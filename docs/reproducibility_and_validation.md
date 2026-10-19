# Reproducibility and validation status

This document separates facts visible in the repository from results that would require a new, successful, independent execution. These caveats are part of the research record and should remain visible until resolved.

## Current status

| Component | What is present | What has not been established |
|---|---|---|
| Simulator modules | Base and extended Python simulation modules | Full behavioral equivalence across environments or an end-to-end experiment run in a clean environment |
| Short-horizon runner | Code for 2,000-, 3,000- and 5,000-day configurations; separate forecast, inventory and ranking outputs | A run of the joined alignment analysis (F03) on real outputs, or a successful complete test run covering the intended configurations |
| 7,300-day notebook | Organized 114-cell working research record, saved outputs, validation cells and result rechecks | Clean-room execution; verification of every saved output; complete reconciliation of Combined Disruption checks |
| Cross-horizon inventory evidence | Thesis-associated summary files were provided during research | Independent 5,000-day inventory evidence, because the supplied 5,000-day outcomes and ranking files duplicate 3,000-day files |

## High-priority findings to resolve

### 1. 5,000-day inventory files duplicate 3,000-day files

In the source files I inspected during the research (not included in this repository), `Inventory Outcomes_5000.csv` has the same contents as `Inventory Outcomes_3000.csv`. The corresponding inventory metric ranking files for 5,000 and 3,000 days are also identical. (Forecast-outcome files for 5,000 and 3,000 days do differ; the duplication affects the inventory files.)

Method: direct byte comparison of the supplied files.
Source: thesis-associated summary files inspected during
research (not in this repository). Uncertainty:
byte-identical files establish that the supplied files are
duplicates; they do not by themselves establish whether a
separate 5,000-day inventory run was performed and its
output mishandled, or no separate run exists.

This means the supplied 5,000-day inventory outcomes do not independently substantiate a separate horizon. The files should be regenerated from the intended 5,000-day experiment, or their provenance should be resolved before a claim relies on them. This repository package does not include the source CSVs or present a regenerated replacement.

### 2. Combined Disruption cells in the 7,300-day notebook: three failed checks, later passing assembly and inventory cells, and a hardcoded locked table

The organized notebook contains three saved error cells in the Combined Disruption section. Their failures are check and file-selection issues, not evidence that the underlying frozen demand is mismatched. Execution counts (`execution_count`) are the provenance evidence in the notebook; notebook order alone is not execution order. **The saved outputs are the historical record; the code of cells 93, 100, 103, 106 and 109 has since been corrected (see `notebooks/README.md` changelog) without re-execution, so the saved outputs of those cells do not reflect the corrected code.**

- **Cells 94–99 (diagnostic searches, executions 33–39) - show the Combined file did not exist yet.** Cell 94 reports both Combined forecast directories as `DOES NOT EXIST`. Cell 96 walks the drive, finds only the Supply `test_forecasts.csv`, and reports `NO EXACT MATCH FOUND` for the Combined test-demand total (17,182,745). Cell 99 lists `forecast_results/`: Demand has only per-model `*_test.csv` files, Supply has `test_forecasts.csv`, and there is no `combined_disruption/` directory. This explains the next failure.
- **Cell 93 (first Combined inventory attempt, execution 32) - failed.** It fell back to the Supply Disruption forecast file (`.../supply_disruption/test_forecasts.csv`) because the Combined forecast file did not exist at that execution, then compared Supply forecast actuals (Normal demand) against Combined frozen demand. Result: `ValueError: Forecast/frozen-demand mismatches: 164610` out of 165,000 rows. This cell produced no inventory output and must not be treated as the Combined result. It is superseded by cell 106. **Code corrected since:** the cross-scenario fallback has been removed from cell 93; the cell now requires the Combined forecast file and fails clearly if it is missing.
- **Cell 100 (Combined assembly, execution 40) - failed.** It used `expected_per_model = 50 * 1000 = 50,000`, but the test window 6,200–7,299 is 1,100 days, so the correct expectation is `50 * 1100 = 55,000` rows per model. Result: `ValueError: Seasonal Naive: expected 50,000 rows, got 55,000`. Execution stopped before saving. **Code corrected since:** the expectation is now `50 * 1100`.
- **Cell 104 (Combined assembly, execution 44) - passed and saved.** It uses the correct 55,000-rows-per-model expectation and per-model totals, reports 0 row mismatches, and saves the Combined forecast file (`.../combined_disruption/test_forecasts.csv`, 165,000 rows, columns `[item, model, split, day, actual, forecast]`, sorted by `[model, item, day]`).
- **Cell 103 (Combined assembly, execution 45 - after cell 104 despite notebook order) - failed.** Its per-row checks found 0 mismatches, but its aggregate total check compared summed actuals across all three models (51,548,235) against a single-model frozen-demand total (17,182,745), which is 3× too small by construction. Result: `ValueError: Total forecast actual != total frozen demand`. Execution stopped before saving, so it did not overwrite cell 104's file. **Code corrected since:** the total check now validates per model.
- **Cell 105 (Combined assembly, execution 46) - passed and saved, overwriting cell 104.** It is a stricter version of cell 104 (explicit 1,100-day window comment, duplicate checks, per-model checks, final asserts). Its data transformation is the same as cell 104's (same inputs, same test-window filter, same type casts, same column order, same sort, same output path). Its output reports the same 165,000 rows, 55,000 per model, 0 mismatches, and the same columns. By execution order (46 > 44, with no other writer of this path in between), the file on disk after cell 105 is cell 105's save.
- **Cell 106 (final Combined inventory experiment, execution 47) - passed.** It requires the Combined forecast file directly (no fallback), verifies forecast actuals per model against frozen Combined demand with 0 mismatches, and completes the inventory run, writing `final_combined_disruption_inventory_results.csv`, a manifest, per-model manifests, and forecast targets to `.../inventory_results/combined_disruption_full/`.

**Downstream provenance - split:**

- **Cells 110–112 (forecast rechecks, executions 55–57) read the file from disk.** Each reads `.../forecast_results/combined_disruption/test_forecasts.csv`. No cell writes that path between cell 105 (execution 46) and cells 110–112, so the file they read is cell 105's save, to the extent the notebook can establish it. They recompute forecast accuracy from that file. Their results do not all agree: cell 110's pooled RMSE (e.g. Seasonal Naïve 26.689412) differs from the mean-of-item-level RMSE in cells 111–112 (26.247419), and MASE differs across cell 110 (0.999805 / 0.859713 / 0.814020), cell 112 (1.078133 / 0.925569 / 0.880432), and the locked table below. The MASE definition used for each value is therefore unresolved in the notebook.
- **Cell 109 (locked master tables, execution 50) does NOT consume the files above.** Its header states `NO SIMULATION, NO FILE SEARCH, NO SCHEMA GUESSING`. It contains zero `read_csv` calls and zero references to variables from cells 93–106. It constructs `inventory_results_df` and `forecast_accuracy_df` from hardcoded literals in code, then derives `ranking_df` from those literals via `rank()` calls, and writes the four `MASTER_*_FINAL.csv` files. There is no programmatic link from cell 106's inventory file or cells 104/105's forecast file to cell 109's tables.
  - The Combined **inventory** literals in cell 109 match cell 106's saved output to displayed precision on all eight reported metrics (e.g. Seasonal Naïve fill rate 0.1384853037 vs 0.138485, unfilled 87,816,644, average destination inventory 155.251704, shipments 335,681,841). This supports - but does not prove - that they were transcribed from cell 106. The transcription itself is not recorded or verified in the notebook.
  - The Combined **forecast MAE/RMSE** literals in cell 109 match the pooled calculations from the file (cell 110: MAE 20.772073 / 17.912968 / 16.966127; RMSE 26.689412 / 23.001942 / 22.134175).
  - The Combined **MASE** literals in cell 109 (0.999708 / 0.862107 / 0.816538) match the “slide” values compared in cell 110, not any MASE calculated from the file in the notebook (cell 110: 0.999805 / 0.859713 / 0.814020; cell 112: 1.078133 / 0.925569 / 0.880432). The denominator and calculation behind the locked MASE values are not recorded in the notebook and remain **unresolved**.

**What remains unresolved:** (a) the locked MASE definition and its source; (b) the pooled-vs-mean-of-item-level RMSE labelling in the locked table; (c) confirmation that cell 109's inventory literals were transcribed from cell 106's file, since no verification step links them; (d) the gaps in execution counts (missing executions 35, 43, 48–49, 51–54) mean preserved execution order is best-effort evidence, not a cryptographic chain - no file hashes or timestamps are recorded in the notebook. A locked result table or a later recheck cell does not by itself establish that all Combined Disruption values are validated. I won't change the locked values or any calculation to reconcile these differences without first writing down the evidence and the proposed fix.

### 3. The alignment calculation lives in `scripts/alignment_analysis.py`, not in the runner

`thesis_short_horizon_experiments.py` writes forecast metrics and inventory metric rankings to separate files. The joined forecast-rank-vs-inventory-rank analysis is implemented separately in `scripts/alignment_analysis.py` (F03): it joins the runner-style forecast and inventory outputs on (horizon, scenario, model), computes rank differences, exact agreement (model-level and complete-ordering, labelled separately), mean |Δ|, descriptive Spearman/Kendall, horizon/scenario breakdowns, and the median-forecast-rank sensitivity. It implements the thesis's stated 6-metric procedure (§4.4 / Appendix B). It does **not** reproduce the thesis's Table 4.2 values, which match a recomputation under the 456-combination framework (see `docs/thesis_traceability_matrix.md` §9.3). This repo isn't a full computational reproduction until the F03 script has run on real experiment outputs.

### 4. The meaning of ranking directions must remain explicit

The thesis keeps forecast error, service, inventory and backlog outcomes distinct and does not use a composite score. Inventory quantity measures also need operational context: less inventory is not automatically preferable if service deteriorates. The runner ranks only the six primary inventory measures defined by the thesis (§4.4 / Appendix B); maximum inventories, final destination backlog, and shipment units are recorded as descriptive values and are not ranked. The F03 alignment script uses the same six-metric primary set. I keep the difference between primary evaluation metrics and descriptive outcomes visible in any consolidated result. The full thesis-to-code mapping is in `docs/thesis_traceability_matrix.md`.

### 5. The short-horizon and 7,300-day LightGBM workflows differ

The 7,300-day Supply Disruption LightGBM implementation (notebook cell 89) refits at each 7-day forecast origin and caps each recursive prediction at zero via `max(0.0, pred)`. The shorter-horizon runner fits one LightGBM model per item on pre-test history and predicts recursively within 7-day blocks without that cap. The 7,300-day Normal LightGBM cells fit once per item and do not cap predictions. These are implementation differences that qualify direct comparisons across horizons; they must not be silently reconciled in documentation or analysis.

## Environment and data requirements

The organized 7,300-day notebook references local paths under `D:\ISOMORPH\...` and expects input/result files that are not included in the repository. No original data environment lock file is supplied. Requirements are listed for the code, but dependency versions from the historical experiment have not been reconstructed here.

The root `.gitignore` excludes generated histories, output folders, environment files and common local artifacts. Keep raw or private simulation output outside the repository unless there is a deliberate, reviewed reason to version a small, documented and non-sensitive result artifact.

## Checks I ran while putting this together

The following checks completed successfully:

- `python -m py_compile` passed for `Supplychaingeo_item50.py`, `Supplychaingeo_item50_v2.py` and `thesis_short_horizon_experiments.py`.
- The primary notebook parsed as valid notebook JSON and contained 114 cells. The organized notebook's **code** was corrected for demonstrable bugs (cells 22, 56, 93, 100, 103, 106, 109; see `notebooks/README.md` changelog) without re-execution; its saved outputs predate those corrections.
- The primary notebook's saved outputs include three error cells (93, 100, 103, all in the Combined Disruption section) and five empty cells; see §2 for the cell-level Combined status.
- Relative Markdown links in the README and documentation files resolved to existing files.

No simulation run, full import/runtime test, notebook re-execution or result reproduction was performed as part of putting this together. A syntax check establishes only that source files parse; it does not prove that imports, full simulations, notebook cells, saved outputs or the thesis findings are correct. A clean validation release should record:

1. exact Python and dependency versions;
2. an executed, documented small smoke-test run;
3. completed scenario/horizon run logs;
4. the alignment-analysis output and validation checks;
5. independent resolution of the duplicated 5,000-day inventory files; and
6. reconciliation of the Combined Disruption notebook checks.

Until then, I describe this as a thesis research codebase with documented validation boundaries, not a fully reproduced computational release.
