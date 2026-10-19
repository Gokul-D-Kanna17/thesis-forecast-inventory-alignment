# Data and artifact manifest

What is included in this repository, what is missing, and why. Nothing
here is a substitute for the frozen source files listed as missing.

## Included

| Artifact | Location | Notes |
|---|---|---|
| Base simulator | `Supplychaingeo_item50.py` | SHA-256 `604b62788548…` recorded |
| Extended simulator (v2) | `Supplychaingeo_item50_v2.py` | SHA-256 `12fe0cdc7a96…` recorded; imports the base module, so both files must stay in the repository root |
| Short-horizon runner | `thesis_short_horizon_experiments.py` | 2,000 / 3,000 / 5,000-day configurations; daily-aggregate inventory metrics (v2), auditable totals, run manifest, overwrite protection, pre-save validation |
| Alignment analysis (F03) | `scripts/alignment_analysis.py` | Joined forecast↔inventory rank alignment; mean-of-item primary + median sensitivity + horizon/scenario breakdowns; synthetic-tested; not run on real outputs |
| Inventory recomputation (F01) | `scripts/recompute_inventory_windows.py` | One common test window, daily-aggregate definitions (v2); synthetic-tested; real-data run blocked |
| Forecast recomputation (F05) | `scripts/recompute_forecast_metrics.py` | One consistent definition + 7300-day adapter, finite-value checks; synthetic-tested; real-data run blocked |
| Test suite | `tests/` | 109 tests, all passing (synthetic fixtures + F04 on the real simulator + runner metric/manifest/validation tests) |
| Organized 7,300-day notebook | `notebooks/thesis_7300day_notebook_organized_plain_text.ipynb` | 114 cells; saved outputs preserved; SHA-256 `26bd7c97…` |
| Protocol, methodology, validation docs | `docs/` | See `docs/README.md` |
| Citation file | `CITATION.cff` | Author + repo URL; no DOI/version/date (intentional - not invented) |

## Missing (not in this repository)

These files live on the author's machine under `D:\ISOMORPH\thesis_frozen\`
(original locations; not accessible from every environment). They are
**not** reproduced, fabricated, or replaced here. The F01/F05 scripts
fail explicitly if they are absent.

**F01 - frozen inventory records (48 files):** per scenario
(`normal`, `demand_disruption_full`, `supply_disruption_full`,
`combined_disruption_full`) × per model (`seasonal_naive`, `ets`,
`lightgbm`) × `daily_records.csv`, `inventory_history.csv`,
`backlog_history.csv`, `shipments.csv`.

**F01/F05 - frozen demand (4 files):**
`thesis_frozen\{normal,demand_disruption,supply_disruption,combined_disruption}\daily_records.csv`
(training series for the MASE denominator + demand cross-checks).

**F05 - forecast files:**
- `forecast_results\demand_disruption\{seasonal_naive_test,ets_test,lightgbm_test}.csv`
- `forecast_results\supply_disruption\test_forecasts.csv`
- `forecast_results\combined_disruption\test_forecasts.csv`
- `forecast_results\normal\test_forecasts.csv` - provenance unresolved:
  no notebook cell writes it; cell 91 searches for it.

**Runner outputs:** no `all_inventory_outcomes.csv`,
`all_test_forecasts.csv`, or forecast-metrics files from the
short-horizon runner exist in this repository (the runner has not
been executed to produce them here).

## License

No license file is included: simulator provenance, ownership, and
redistribution permission have not been established.

## Known duplicate (do not use as independent evidence)

The thesis-associated supplied files `Inventory_Outcomes_5000.csv`
and `Inventory_Outcomes_3000.csv` are byte-for-byte identical
(verified by direct comparison), as are the corresponding 5,000- and
3,000-day inventory ranking files. The 5,000-day forecast files do
differ. The 5,000-day inventory evidence is therefore not
independently substantiated by those files. These supplied files are
not included in this repository. Method, source, and uncertainty:
`docs/reproducibility_and_validation.md` §1.

## Consequences

- No thesis numerical result in this package has been recomputed
  from the original experimental records (see
  `docs/validation_and_limitations.md`). Consistency checks
  calculated from values printed in the thesis are labelled as
  such in `docs/thesis_traceability_matrix.md`.
- The F01/F05 scripts and the F03 alignment script are validation
  tooling, tested on synthetic fixtures. Running them on the frozen
  files above is the remaining step for real-data verification.
- The `.gitignore` excludes generated histories, output folders, and
  large per-run CSVs. Do not commit raw simulation output without a
  deliberate, reviewed reason.
