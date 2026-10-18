# From Forecast Accuracy to Inventory Decisions

**Evaluating forecast-to-decision alignment under normal and disrupted supply-chain conditions**

Master's thesis research project | Python · Time-series forecasting · Supply-chain simulation · Inventory analytics

**Research focus:** Does a forecasting method's rank by statistical accuracy correspond to its rank by downstream inventory outcomes? This project examines that relationship across operating scenarios and simulation horizons. It does **not** seek to declare one forecasting model universally best.

## The problem

Forecasting systems are often compared using prediction-error metrics. In an inventory system, however, a forecast is an input to a decision process: replenishment, transit, stock availability, backlog, and the operating environment shape what happens after a prediction is made. Better forecast accuracy and better inventory outcomes are related questions, but they are not the same outcome.

This study evaluates forecasting methods twice: first as predictors of demand, then by the inventory outcomes observed when their forecasts are used by a common downstream decision mechanism. The central object of analysis is the **alignment between the two ranking systems**, including the cases where they disagree.

## Research design at a glance

| Element | Design |
|---|---|
| Supply-chain setting | Synthetic, multi-echelon, FMCG-like network |
| Product scope | 50 stock-keeping units (SKUs) |
| Forecasting methods | Seasonal Naïve, Exponential Smoothing (ETS), LightGBM |
| Forecast horizon | 7 days |
| Operating scenarios | Normal, Demand Disruption, Supply Disruption, Combined Disruption |
| Simulation horizons | 2,000, 3,000, 5,000 and 7,300 days |
| Forecast-accuracy measures | MAE, RMSE and MASE (lower is better) |
| Decision outcomes | Service/fill rate, unfilled demand, destination inventory, network inventory and backlog measures |
| Main comparison | Metric-specific forecast ranks versus metric-specific inventory-outcome ranks |

The horizons are separate experiment configurations, not four independent statistical replications. The shorter-horizon experiments and the 7,300-day notebook also have implementation differences; see [the experiment protocol](docs/experiment_protocol.md) and [validation notes](docs/reproducibility_and_validation.md).

## Research workflow (conceptual)

```mermaid
flowchart TD
    A[Simulated demand and operating scenario] --> B[7-day-ahead forecasts]
    B --> C[Forecast-error metrics: MAE, RMSE, MASE]
    B --> D[Forecasts supplied to inventory decision mechanism]
    A --> D
    D --> E[Service, inventory and backlog outcomes]
    C --> F[Forecast-method rankings]
    E --> G[Inventory-metric rankings]
    F --> H[Compare ranks and quantify alignment]
    G --> H
```

This diagram summarizes the thesis design. The workflow separates prediction quality from operational outcomes. Forecast metrics and inventory objectives are **not** collapsed into a weighted composite score. A high fill rate is desirable; lower unfilled demand and backlog are generally desirable; lower inventory is interpreted alongside service, rather than as an unqualified objective. The thesis does not construct monetary holding, ordering, or stockout costs and therefore does not claim cost savings or economic superiority.

## What the analysis examines

- **Forecast accuracy:** model-level MAE, RMSE and MASE, with item-level values aggregated using means and medians where the underlying result tables provide them.
- **Inventory outcomes:** fill rate, total unfilled demand, average destination inventory, average destination backlog, maximum destination backlog and average total network inventory as the primary operational measures. Maximum inventory, final backlog and shipment totals are treated as descriptive measures in the thesis framework.
- **Rank alignment:** rank difference, absolute rank difference, exact model-rank agreement and descriptive rank correlation. With only three forecasting methods, rank correlations are descriptive rather than strong inferential evidence.
- **Robustness and context:** whether the relationship varies by disruption scenario, simulation horizon and aggregation choice.

## Findings and evidential status

The thesis reports **limited rather than one-to-one ranking agreement** between forecast-accuracy ranks and inventory-decision ranks. This repository does not present a single blended agreement percentage, because the percentage depends on the alignment definition: complete-ordering agreement (all three models in the same order on a given metric) and model-level rank equality (a single model's forecast rank equals its inventory rank) are different estimands, and the six-primary-metric framework and the wider descriptive-metric framework give different results. Mean absolute rank differences were reported near one rank position. These are descriptive results, not inferential estimates.

**Important qualification:** this repository has not yet independently reproduced the complete alignment analysis end to end on real experiment outputs. Source-file audits found that the supplied 5,000-day inventory-outcome and inventory-ranking files are byte-for-byte duplicates of the 3,000-day counterparts. The 7,300-day notebook also contains failed Combined Disruption check cells alongside later passing assembly and inventory cells (see validation notes for the cell-level status). Consequently, those files do not independently validate the reported 5,000-day inventory evidence, and the cross-horizon summaries should not be presented as fully verified until the source outputs are reconciled. The known issues and protocol differences are documented in [Validation and reproducibility status](docs/reproducibility_and_validation.md) and [Validation and limitations](docs/validation_and_limitations.md).

This distinction is central to the project: results should be interpreted in light of how they were produced and checked, not only how they are presented.

## Repository map

```text
.
├── README.md
├── requirements.txt
├── .gitignore
├── .gitattributes
├── CITATION.cff
├── Supplychaingeo_item50.py
├── Supplychaingeo_item50_v2.py
├── thesis_short_horizon_experiments.py
├── scripts/
│   ├── alignment_analysis.py            # F03: forecast↔inventory rank alignment
│   ├── recompute_inventory_windows.py   # F01: inventory outcomes, one common test window
│   └── recompute_forecast_metrics.py    # F05: forecast metrics, one consistent definition
├── tests/
│   ├── test_alignment_analysis.py
│   ├── test_ema_equivalence.py          # F04: EMA injection equivalence (real simulator)
│   ├── test_recompute_inventory_windows.py
│   ├── test_recompute_forecast_metrics.py
│   └── test_runner_inventory_metrics.py # runner aggregation, validation, manifest, overwrite
├── notebooks/
│   ├── README.md
│   ├── thesis_7300day_notebook_organized_plain_text.ipynb
│   └── archive/
│       ├── README.md
│       └── thesis_working_notebook_7300_days.ipynb
└── docs/
    ├── README.md
    ├── experiment_protocol.md
    ├── reproducibility_and_validation.md
    ├── methodology.md                   # F02/F05 definitions
    ├── validation_and_limitations.md    # F01–F05 status, verified vs unverified
    ├── data_manifest.md                 # what is included / missing
    ├── discrepancy_report.md            # F05 vs locked/slide values (BLOCKED)
    └── stage1_closeout_report.md
```

### Main files

- **`Supplychaingeo_item50.py`** — base supply-chain simulation model, including the network, item and node structures, routing/allocation logic and day-level simulation.
- **`Supplychaingeo_item50_v2.py`** — extended simulation with disruption and scenario-control functionality. It imports the base module, so both Python modules must stay together in the repository root.
- **`thesis_short_horizon_experiments.py`** — runner for the 2,000-, 3,000- and 5,000-day configurations. It freezes a scenario's demand series for model comparisons, evaluates forecasts, runs the inventory experiments, and writes forecast summaries and inventory-metric rankings. Inventory levels use daily aggregates (sum across items/nodes per day, then mean/max across test days; aggregation version `inventory-metrics-v2-daily-aggregate`), records the auditable totals (`total_test_demand`, `total_served_from_stock`, `total_unfilled_demand`), writes a run manifest (`run_manifest.json`), refuses a non-empty output directory without `--overwrite`, and validates forecast coverage and the output schema before saving aggregate results.
- **`scripts/alignment_analysis.py`** — the joined forecast-rank-versus-inventory-rank alignment analysis (F03). It recomputes ranks from values, validates inputs (item sets, models, daily coverage, common test window, experiment grid, finite values), cross-checks the item metrics file by recomputing item-level MAE/RMSE from the day-level forecast records, and reports rank differences, both agreement estimands, descriptive correlations, a median-of-item sensitivity, and horizon/scenario breakdowns rebuilt from the same alignment table. It has not yet been run on real experiment outputs.
- **`scripts/recompute_inventory_windows.py`** — F01 recomputation: inventory outcomes over one common test window from frozen per-model records, with daily-aggregate definitions (v2), validation and the fill-rate identity check. Real-data execution is blocked pending the frozen files (see `docs/data_manifest.md`).
- **`scripts/recompute_forecast_metrics.py`** — F05 recomputation: per-item MAE/RMSE/MASE with the training-period scale, mean across items, finite-value checks, plus a 7300-day adapter for the notebook forecast formats. Real-data execution is blocked pending the frozen files.
- **`notebooks/thesis_7300day_notebook_organized_plain_text.ipynb`** — the primary organized research notebook for the 7,300-day experiment. It records data checks, exploratory analyses, forecast experiments, inventory experiments and later result rechecks.
- **`docs/`** — protocol, methodology, validation status, and data manifest. Sharing drafts (professor note, email/LinkedIn drafts, license note) are kept outside this repository.

## Getting started

### 1. Create an environment and install dependencies

Python 3.9 or newer is the target for the short-horizon runner. The original 7,300-day notebook metadata references a Python 3.12 environment named `ISOMORPH`; an exact historical environment lock file is not included (known limitation: dependencies are unpinned).

```bash
python -m venv .venv
```

Activate the environment, then run:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Run the test suite

```bash
python -m unittest discover -s tests
```

The suite covers the alignment analysis, the EMA equivalence test (which runs the real simulator on synthetic inputs), the F01/F05 recomputation utilities, and the runner's inventory-metric, ranking-direction, validation, manifest, and overwrite logic on synthetic fixtures — 109 tests in total. Passing tests verify the **code logic**; they do not verify thesis results, which require real experiment outputs (see `docs/validation_and_limitations.md`). The runner tests import the runner, so the dependencies from `requirements.txt` must be installed first.

### 3. Check Python syntax without launching experiments

```bash
python -m py_compile \
  Supplychaingeo_item50.py \
  Supplychaingeo_item50_v2.py \
  thesis_short_horizon_experiments.py
```

This is a syntax check only; it does not validate the simulation or reproduce thesis results.

### 4. Run a small configuration when ready

The following command starts the 2,000-day Normal scenario. It is an actual simulation run and may take time; it is **not** executed automatically when the repository is installed.

```bash
python thesis_short_horizon_experiments.py \
  --output-dir thesis_short_runs \
  --horizons 2000 \
  --scenarios normal
```

The runner writes generated outputs under the selected output directory, which is excluded from Git, plus a run manifest (`run_manifest.json`). It refuses a non-empty output directory unless `--overwrite` is given. See [the experiment protocol](docs/experiment_protocol.md) before running additional configurations.

### 5. Recompute from frozen outputs (when available)

The F01/F05 scripts operate on frozen source files that are **not** in this repository (see `docs/data_manifest.md` for the exact paths). Their CLIs are documented in `docs/validation_and_limitations.md`; they fail explicitly if any required file is missing.

## Reproducibility boundaries

This repository is a research-code and audit-trail package, **not yet a one-command reproduction of every thesis table**.

- The joined alignment analysis is now implemented (`scripts/alignment_analysis.py`, synthetic-tested), but it has not been run on real experiment outputs, because no runner outputs exist in the repository and the 7,300-day source files are not included.
- The 7,300-day notebook refers to local Windows paths and expects simulation data/results that are not included here. It has not been re-executed in a clean environment as part of this package.
- The notebook contains three saved error cells in the Combined Disruption section (cells 93, 100, 103) alongside later passing assembly and inventory cells (104–106). The code of cells 93, 100, 103, 106 and 109 has been corrected for demonstrable bugs (fallback removed, row-count and per-model checks fixed, test-window aggregation, snapshot labelling — see `notebooks/README.md`), but the notebook has NOT been re-executed after those corrections, so the saved outputs predate the corrected code. The locked master table (cell 109) is hardcoded literals with no file reads and no programmatic link to the earlier cells, and its MASE values do not match any in-notebook calculation from the Combined file (see validation notes). Its saved outputs should not all be treated as authoritative without reconciliation.
- The 7,300-day Supply Disruption LightGBM procedure differs from the shorter-horizon procedure in refitting behavior and prediction clipping.
- A completed experiment run, a saved output, and an independently validated result are different statuses. Do not conflate them.

See [docs/reproducibility_and_validation.md](docs/reproducibility_and_validation.md) and [docs/validation_and_limitations.md](docs/validation_and_limitations.md) for detail. A clean, recorded end-to-end run on real outputs remains the main work needed before this repository can claim full computational reproducibility of the thesis results.

## Skills demonstrated

The work provides concrete examples of:

- time-series forecasting and lag/rolling-feature engineering;
- LightGBM and statistical exponential smoothing;
- stochastic multi-echelon supply-chain simulation;
- inventory service, backlog and stock measurement;
- metric-specific ranking and forecast-to-decision comparison;
- data validation, auditability and methodological qualification;
- Python, pandas, NumPy, scikit-learn, statsmodels, LightGBM and Jupyter.

## Research scope and limitations

The environment is synthetic, the model set is limited to three forecasting methods, the forecast horizon is fixed at seven days, and inventory performance is evaluated using separate operational measures rather than an explicit economic objective. Findings should be interpreted within those boundaries; they are not evidence of realized company savings or universal model superiority.

## Author

**Gokul Kanna Durairaj** · Master's thesis in Data Science – Business Analytics

[LinkedIn](https://www.linkedin.com/in/gokuldkanna/)
