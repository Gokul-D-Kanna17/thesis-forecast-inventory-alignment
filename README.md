# Forecast Accuracy and Inventory-Decision Alignment

Research-code repository for the master's thesis **“From Forecast Accuracy to Inventory Decisions: Evaluating Forecast-to-Decision Alignment under Normal and Disrupted Supply-Chain Conditions.”**

The thesis studies whether demand-forecast accuracy rankings align with inventory-decision rankings across simulation horizons and supply-chain scenarios. The focus is alignment between rankings, not identifying one universally best forecasting model.

## Contents

```text
.
├── README.md
├── requirements.txt
├── .gitignore
├── .gitattributes
├── Supplychaingeo_item50.py
├── Supplychaingeo_item50_v2.py
├── thesis_short_horizon_experiments.py
├── docs/
│   └── experiment_protocol.md
└── notebooks/
    └── archive/
        ├── README.md
        └── thesis_working_notebook_7300_days.ipynb
```

- `Supplychaingeo_item50.py`: base supply-chain simulator.
- `Supplychaingeo_item50_v2.py`: extended simulator; imports the base module. Keep both files in the repository root because the import path currently expects this layout.
- `thesis_short_horizon_experiments.py`: runner for 2,000-, 3,000-, and 5,000-day experiments.
- `notebooks/archive/thesis_working_notebook_7300_days.ipynb`: preserved working notebook for historical reference. It is not guaranteed to run in a clean environment and may contain old outputs and machine-specific paths; treat its outputs as historical, not automatically authoritative.

## Environment

Use Python 3.9 or newer. Install the core dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run the short-horizon experiments

Run all configured horizons and scenarios:

```bash
python thesis_short_horizon_experiments.py --output-dir thesis_short_runs
```

Run only the 2,000-day Normal scenario:

```bash
python thesis_short_horizon_experiments.py --output-dir thesis_short_runs --horizons 2000 --scenarios normal
```

The full run can be computationally expensive. Start with one horizon and one scenario to check the environment before launching all experiments. Generated output is written to the output directory and is excluded from Git by `.gitignore`.

## Current status and important qualification

The runner is prepared to generate forecast metrics, inventory outcomes, and inventory-metric rankings. Creating the script does **not** mean the experiments have been executed or that results are verified. Before using output in the thesis, run the experiment, retain its configuration and logs, and review the generated files.

The current runner writes forecast-accuracy summaries and inventory rankings separately. It does not yet write a dedicated joined forecast-rank-versus-inventory-rank alignment summary. That gap must be addressed and checked before treating the short-horizon workflow as a complete implementation of the thesis's primary analysis.

No results are committed by default. Commit only curated, verified summary tables if there is a clear reason to version them. Do not commit generated daily histories, raw/intermediate outputs, secrets, credentials, or unrelated files from the working directory.

## Reproducibility notes

The runner fixes a seed and defines the split windows in code. Keep the code, scenario settings, split configuration, and software environment together when recording an experiment. Record the actual package versions used for each final run; this starter does not claim that the original notebook's exact environment has been reconstructed.
