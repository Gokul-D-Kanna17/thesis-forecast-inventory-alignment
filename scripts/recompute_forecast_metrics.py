"""F05 - Forecast-metric recomputation from forecast outputs + training data.

One consistent definition across all models, scenarios, and horizons:
  - MAE and RMSE per item over the same test window (test_start..test_end).
  - MASE per item = item MAE / item training-period naive seasonal-error
    scale, where the scale is mean |train[7:] - train[:-7]| over that
    item's training series (days 0..train_end, from the frozen demand
    file). This matches the primary implementation (notebook cells 67,
    81, 89; runner fit_and_forecast).
  - Aggregation: mean across items. Pooled errors and pooled MASE are
    NEVER substituted.

Inputs:
  --forecast-file (repeatable) + --forecast-format (repeatable, parallel):
    "runner"          : columns model, item, day, forecast, actual
                        (scenario/horizon added by the caller).
    "notebook_per_row": columns item, model, split, day, actual, forecast
                        (notebook Supply cell 89 and Combined cell 105;
                        split must be "test").
    "notebook_demand" : columns item, day, forecast, actual, one file per
                        model; the model is inferred from the filename
                        (seasonal_naive_test.csv -> Seasonal Naive,
                        ets_test.csv -> ETS, lightgbm_test.csv -> LightGBM;
                        notebook Demand cell 81).
  --demand-file: frozen demand CSV (day, item, demand), full horizon.
    The training series is days 0..train_end; forecast actuals are
    cross-checked against this file for test days.
  --scenario, --train-end, --test-start, --test-end.
  --locked-values (optional): CSV with scenario, model, MAE, RMSE, MASE,
    source (e.g. locked table / slides) for the discrepancy report.

The 7300-day notebook horizon is NOT covered by the short-horizon runner.
The notebook formats above ARE the 7300-day adapter: they are implemented
and tested separately from the runner format, using the actual notebook
schemas (verified from the notebook source). No missing outputs are
invented: if a forecast file does not exist, the script fails.

Validation (all failures are explicit errors):
  - Required columns; no missing values; no non-finite (NaN/inf)
    forecast, actual, or frozen-demand values; no duplicate (model, item, day).
  - Complete daily coverage: for every (model, item), exactly one row per
    day test_start..test_end.
  - Identical item sets across models; common test window (parameters).
  - Forecast/actual alignment: every forecast row has an actual; actuals
    equal frozen demand for the same (day, item) on test days.
  - Training series complete (days 0..train_end per item, no gaps/dups);
    train_end < test_start; MASE denominator > 0 per item.

Outputs (output_dir):
  recomputed_forecast_metrics_per_item.csv
  recomputed_forecast_metrics_summary.csv (mean across items)
  recomputed_forecast_metadata.json (definitions, window, train_end,
    aggregation, inputs, validation, provenance)
  discrepancy_report.csv (only with --locked-values): per (scenario,
    model, metric) status match / differ / cannot-check.

No thesis results are produced from synthetic fixtures. The CLI is for
real forecast outputs only; unit tests call the functions on synthetic
fixtures and never write thesis outputs.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

SEASONALITY = 7
EXPECTED_MODELS = ("Seasonal Naive", "ETS", "LightGBM")
DEMAND_FILENAME_TO_MODEL = {
    "seasonal_naive_test.csv": "Seasonal Naive",
    "ets_test.csv": "ETS",
    "lightgbm_test.csv": "LightGBM",
}


def adapt_forecast_file(path: Path, fmt: str) -> pd.DataFrame:
    """Convert one forecast file to the canonical schema.

    Canonical columns: model, item, day, forecast, actual.
    """
    if not path.exists():
        raise FileNotFoundError(f"forecast file not found: {path}")
    df = pd.read_csv(path)
    if fmt == "runner":
        required = ["model", "item", "day", "forecast", "actual"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: runner format missing columns: {missing}")
        out = df[required].copy()
    elif fmt == "notebook_per_row":
        required = ["item", "model", "split", "day", "actual", "forecast"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: notebook_per_row format missing columns: {missing}")
        if set(df["split"].unique().tolist()) != {"test"}:
            raise ValueError(f"{path}: split column must be exactly 'test' in every row")
        out = df[["model", "item", "day", "forecast", "actual"]].copy()
    elif fmt == "notebook_demand":
        required = ["item", "day", "forecast", "actual"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{path}: notebook_demand format missing columns: {missing}")
        model = DEMAND_FILENAME_TO_MODEL.get(path.name)
        if model is None:
            raise ValueError(
                f"{path}: notebook_demand format requires a filename in "
                f"{sorted(DEMAND_FILENAME_TO_MODEL)} to infer the model"
            )
        out = df[required].copy()
        out["model"] = model
        out = out[["model", "item", "day", "forecast", "actual"]]
    else:
        raise ValueError(f"unknown forecast format: {fmt}")
    out["day"] = out["day"].astype(int)
    out["item"] = out["item"].astype(str)
    out["model"] = out["model"].astype(str)
    out["forecast"] = out["forecast"].astype(float)
    out["actual"] = out["actual"].astype(float)
    return out


def _validate_forecasts(forecasts: pd.DataFrame, test_start: int, test_end: int) -> None:
    if forecasts.empty:
        raise ValueError("no forecast rows")
    if forecasts[["model", "item", "day", "forecast", "actual"]].isna().any().any():
        raise ValueError("missing values in forecast rows")
    for col in ("forecast", "actual"):
        vals = pd.to_numeric(forecasts[col], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(vals).all():
            raise ValueError(
                f"non-finite or non-numeric values in forecast column {col}; "
                "non-finite values must never silently produce a metric"
            )
    if bool(forecasts.duplicated(subset=["model", "item", "day"]).any()):
        raise ValueError("duplicate (model, item, day) forecast rows")
    models = sorted(forecasts["model"].unique().tolist())
    if models != sorted(EXPECTED_MODELS):
        raise ValueError(
            f"expected exactly models {sorted(EXPECTED_MODELS)}, got {models}"
        )
    item_sets = {
        model: set(forecasts[forecasts["model"] == model]["item"].unique().tolist())
        for model in EXPECTED_MODELS
    }
    first = item_sets[EXPECTED_MODELS[0]]
    for model, items in item_sets.items():
        if items != first:
            raise ValueError(f"model {model} item set {sorted(items)} != {sorted(first)}")
    expected_days = set(range(test_start, test_end + 1))
    for (model, item), group in forecasts.groupby(["model", "item"]):
        days = set(group["day"].tolist())
        if days != expected_days:
            missing = sorted(expected_days - days)
            extra = sorted(days - expected_days)
            raise ValueError(
                f"forecast coverage incomplete for ({model}, {item}): "
                f"missing days {missing[:5]}{'...' if len(missing) > 5 else ''}, "
                f"extra days {extra[:5]}{'...' if len(extra) > 5 else ''}"
            )


def _load_demand(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"frozen demand file not found: {path}")
    df = pd.read_csv(path, usecols=["day", "item", "demand"])
    if df[["day", "item", "demand"]].isna().any().any():
        raise ValueError(f"{path}: missing values in frozen demand")
    demand_vals = pd.to_numeric(df["demand"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(demand_vals).all():
        raise ValueError(f"{path}: non-finite or non-numeric values in frozen demand")
    if bool(df.duplicated(subset=["day", "item"]).any()):
        raise ValueError(f"{path}: duplicate (day, item) frozen-demand rows")
    df["day"] = df["day"].astype(int)
    df["item"] = df["item"].astype(str)
    df["demand"] = df["demand"].astype(float)
    return df


def _training_scales(demand: pd.DataFrame, train_end: int, items: list[str]) -> dict[str, float]:
    """Per-item MASE denominator from the training series (days 0..train_end)."""
    scales = {}
    for item in items:
        series = demand[(demand["item"] == item) & (demand["day"] <= train_end)].sort_values("day")
        days = series["day"].tolist()
        if days != list(range(0, train_end + 1)):
            raise ValueError(
                f"training series for item {item} is incomplete: "
                f"{len(days)} rows over [0, {train_end}] (gaps or missing days)"
            )
        values = series["demand"].to_numpy(dtype=float)
        denom = float(abs(values[SEASONALITY:] - values[:-SEASONALITY]).mean())
        if denom <= 0:
            raise ValueError(
                f"MASE denominator for item {item} is {denom} (training series "
                "is exactly 7-periodic); MASE undefined"
            )
        scales[item] = denom
    return scales


def compute_metrics(forecasts: pd.DataFrame, demand: pd.DataFrame, scenario: str,
                    train_end: int, test_start: int, test_end: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute per-item and mean-across-items MAE/RMSE/MASE."""
    if train_end >= test_start:
        raise ValueError(f"train_end {train_end} must be < test_start {test_start}")
    _validate_forecasts(forecasts, test_start, test_end)
    items = sorted(forecasts["item"].unique().tolist())
    # Forecast/actual alignment against frozen demand on test days.
    merged = forecasts.merge(
        demand, on=["day", "item"], how="left", suffixes=("", "_frozen")
    )
    if merged["demand"].isna().any():
        missing = merged[merged["demand"].isna()][["model", "item", "day"]].head(3).to_dict("records")
        raise ValueError(f"forecast rows without frozen demand: {missing}")
    mismatch = merged[merged["actual"] != merged["demand"]]
    if not mismatch.empty:
        first = mismatch.iloc[0]
        raise ValueError(
            f"forecast actual != frozen demand at model={first['model']}, "
            f"item={first['item']}, day={first['day']}: "
            f"{first['actual']} vs {first['demand']}"
        )
    scales = _training_scales(demand, train_end, items)
    per_item_rows = []
    for (model, item), group in forecasts.groupby(["model", "item"]):
        err = (group["actual"] - group["forecast"]).to_numpy(dtype=float)
        mae = float(abs(err).mean())
        rmse = float(math.sqrt((err ** 2).mean()))
        mase = mae / scales[item]
        per_item_rows.append({"scenario": scenario, "model": model, "item": item,
                              "MAE": mae, "RMSE": rmse, "MASE": mase})
    per_item = pd.DataFrame(per_item_rows)
    summary = (
        per_item.groupby(["scenario", "model"])[["MAE", "RMSE", "MASE"]]
        .mean().reset_index()
        .rename(columns={"MAE": "mean_MAE", "RMSE": "mean_RMSE", "MASE": "mean_MASE"})
    )
    return per_item, summary


def discrepancy_report(summary: pd.DataFrame, locked: pd.DataFrame,
                       atol: float = 1e-6, rtol: float = 1e-6) -> pd.DataFrame:
    """Compare recomputed means against locked/slide values.

    Status per (scenario, model, metric): match / differ / cannot-check
    (locked value absent). Never silently reconciles: differ rows carry
    the signed difference.
    """
    rows = []
    for _, srow in summary.iterrows():
        for metric, col in (("MAE", "mean_MAE"), ("RMSE", "mean_RMSE"), ("MASE", "mean_MASE")):
            match = locked[
                (locked["scenario"] == srow["scenario"]) & (locked["model"] == srow["model"])
            ]
            if match.empty or pd.isna(match.iloc[0][metric]):
                rows.append({"scenario": srow["scenario"], "model": srow["model"],
                             "metric": metric, "recomputed": srow[col],
                             "locked": None, "difference": None, "status": "cannot-check"})
                continue
            locked_val = float(match.iloc[0][metric])
            diff = float(srow[col]) - locked_val
            status = "match" if abs(diff) <= atol + rtol * abs(locked_val) else "differ"
            rows.append({"scenario": srow["scenario"], "model": srow["model"],
                         "metric": metric, "recomputed": float(srow[col]),
                         "locked": locked_val, "difference": diff, "status": status})
    return pd.DataFrame(rows)


def recompute(forecast_files: list[tuple[Path, str]], demand_file: Path, scenario: str,
              train_end: int, test_start: int, test_end: int,
              locked_file: Path | None = None) -> dict:
    """Run the full F05 recomputation; return DataFrames + metadata."""
    if test_start > test_end:
        raise ValueError(f"test_start {test_start} > test_end {test_end}")
    if not forecast_files:
        raise ValueError("no forecast files given")
    parts = [adapt_forecast_file(p, fmt) for p, fmt in forecast_files]
    forecasts = pd.concat(parts, ignore_index=True)
    demand = _load_demand(demand_file)
    per_item, summary = compute_metrics(forecasts, demand, scenario, train_end, test_start, test_end)
    metadata = {
        "script": "recompute_forecast_metrics.py (F05)",
        "scenario": scenario,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "definitions": {
            "MAE": "per-item mean |actual - forecast| over the test window",
            "RMSE": "per-item sqrt(mean (actual - forecast)^2) over the test window",
            "MASE": "per-item MAE / mean |train[7:] - train[:-7]| over the item's training series (days 0..train_end)",
            "aggregation": "mean across items; pooled errors and pooled MASE are never substituted",
            "training_scale": "training-period 7-lag seasonal-naive denominator, per item",
        },
        "inputs": {
            "forecast_files": [{"path": str(p), "format": fmt} for p, fmt in forecast_files],
            "demand_file": str(demand_file),
            "locked_file": str(locked_file) if locked_file else None,
        },
        "validation": "item sets identical across models; complete daily coverage; "
                      "forecast actuals equal frozen demand on test days; "
                      "training series complete; MASE denominators > 0.",
        "provenance": "Recomputed from forecast outputs + frozen demand listed in inputs. "
                      "No values are copied from the locked table or slides.",
    }
    out: dict = {"per_item": per_item, "summary": summary, "metadata": metadata}
    if locked_file is not None:
        if not locked_file.exists():
            raise FileNotFoundError(f"locked-values file not found: {locked_file}")
        locked = pd.read_csv(locked_file)
        out["discrepancy"] = discrepancy_report(summary, locked)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-file", action="append", required=True,
                        help="forecast CSV (repeatable)")
    parser.add_argument("--forecast-format", action="append", required=True,
                        help="format per --forecast-file: runner | notebook_per_row | notebook_demand")
    parser.add_argument("--demand-file", required=True, help="frozen demand CSV (day, item, demand)")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--train-end", type=int, required=True)
    parser.add_argument("--test-start", type=int, required=True)
    parser.add_argument("--test-end", type=int, required=True)
    parser.add_argument("--locked-values", help="optional locked/slide values CSV for the discrepancy report")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if len(args.forecast_file) != len(args.forecast_format):
        raise SystemExit("--forecast-file and --forecast-format must be given the same number of times")
    result = recompute(
        [(Path(p), fmt) for p, fmt in zip(args.forecast_file, args.forecast_format)],
        Path(args.demand_file), args.scenario, args.train_end, args.test_start, args.test_end,
        Path(args.locked_values) if args.locked_values else None,
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result["per_item"].to_csv(out_dir / "recomputed_forecast_metrics_per_item.csv", index=False)
    result["summary"].to_csv(out_dir / "recomputed_forecast_metrics_summary.csv", index=False)
    (out_dir / "recomputed_forecast_metadata.json").write_text(json.dumps(result["metadata"], indent=2))
    if "discrepancy" in result:
        result["discrepancy"].to_csv(out_dir / "discrepancy_report.csv", index=False)
    print(f"wrote {len(result['summary'])} summary rows to {out_dir}")


if __name__ == "__main__":
    main()
