# Research notebooks

## Primary notebook: 7,300-day experiment

[`thesis_7300day_notebook_organized_plain_text.ipynb`](thesis_7300day_notebook_organized_plain_text.ipynb) is the primary organized notebook associated with the thesis. It contains 114 cells in 10 numbered sections:

1. environment setup and source-data loading;
2. data validation and structural checks;
3. demand structure and seasonality exploration;
4. forecasting dataset and feature preparation;
5. forecasting experiments (including Seasonal Naïve, ETS and LightGBM for Normal);
6. inventory decision experiment - Normal;
7. Demand Disruption experiment;
8. Supply Disruption experiment;
9. Combined Disruption experiment; and
10. locked master results and forecast rechecks.

The notebook is preserved as a research record; its cells and saved outputs have not been rewritten as part of packaging this repo. It is **not a clean-room reproducibility guarantee**. It references local Windows files under `D:\ISOMORPH\...`, depends on external simulation data, contains five empty placeholder cells, and contains three saved error cells in the Combined Disruption section (cells 93, 100, 103) alongside later passing assembly and inventory cells (104–106). The locked master table (cell 109) is hardcoded literals with no file reads, and its MASE values do not match any in-notebook calculation from the Combined file. Review [the validation notes](../docs/reproducibility_and_validation.md) before relying on a saved result.

### Corrections applied to the organized notebook (code only, not re-executed)

The organized notebook's code was corrected for demonstrable bugs. Cell indices are unchanged (no cells inserted or deleted). **I have NOT re-executed the notebook after these corrections** (the frozen source data aren't on this machine), so the saved outputs predate the corrections and do not reflect the corrected code. Don't cite a saved output of a corrected cell as the result of the corrected code.

| Cell | Correction |
| --- | --- |
| 22 | `!pip install matplotlib` removed; dependency installation belongs in the environment setup (`requirements.txt`). |
| 56 | `!pip install lightgbm` removed; same reason. |
| 93 | Cross-scenario forecast-file fallback removed: the Combined experiment now requires its own `forecast_results/combined_disruption/test_forecasts.csv` and raises `FileNotFoundError` if it is missing. Previously it silently fell back to Demand / Normal / Supply files (the actuals check then failed with 164,610 mismatches). |
| 100 | Expected rows per model corrected from `50 * 1000` (50,000) to `50 * 1100` (55,000): the test window is days 6200–7299 inclusive = 1,100 days × 50 items. |
| 103 | Total-demand check corrected to validate **per model**: each model's actuals must separately equal the frozen Combined demand. Previously it summed actuals across all three models (3× the single-scenario total) and compared that to one model's demand, which can never match. |
| 106 | Primary Combined inventory metrics now use the **test window (days 6200–7299)** instead of the full 7,300-day horizon, and destination levels use **daily aggregates** (sum across items per day, then mean/max/final across test days). Full-horizon demand is kept as a separately labelled `full_horizon_demand` descriptive, never mixed into test-window metrics. Remaining definitional difference: this cell's destination levels still use the before-ship columns (`dest_on_hand_end_before_ship`, `dest_backlog_end_before_ship`), while the runner / F01 script use end-of-day snapshots - reconcile before comparing (see `docs/methodology.md` §10). |
| 109 | Locked master table explicitly labelled an **unverified historical snapshot** (hardcoded literals, not recomputed from source outputs). Values unchanged; do not treat as validated evidence. |

In the corrected cells, the machine-specific base path is now configurable: set the `THESIS_DATA_ROOT` environment variable to the directory containing the `thesis_frozen/` tree; it defaults to `D:\ISOMORPH` when unset. Other cells still carry their original `D:\ISOMORPH\...` literals as part of the research record.

## Running notebooks

Install the packages in the root `requirements.txt`, open the notebook in Jupyter, and adapt data paths only after placing the required source data in an explicitly configured local environment. Do not commit private, raw or generated daily simulation histories. A successful notebook open or cell execution is not equivalent to verification of every downstream result.
