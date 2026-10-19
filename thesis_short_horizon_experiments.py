"""Short-horizon thesis experiments: forecast accuracy vs inventory decisions.

Runs 2,000-, 3,000-, and 5,000-day simulations for Normal, Demand Disruption,
Supply Disruption, and Combined Disruption. Uses the supplied simulator modules
in the same directory as this script.

Forecast models: Seasonal Naive, ETS level, LightGBM.
Forecast horizon: 7 days. No composite score or overall model winner is made.

Inventory metric definitions (aggregation version
"inventory-metrics-v2-daily-aggregate"): destination inventory, destination
backlog, and network inventory are DAILY AGGREGATES - each day's value is the
sum across items (and across nodes for network inventory); the mean and
maximum are taken across test days, and the final backlog is the last
test day's aggregate. This matches the 7,300-day notebook's aggregation
(groupby day, sum, then mean/max). Earlier versions of this runner used
per-row (day, item) means and single-record maxima, which are not the same
quantities; do not compare corrected outputs to per-row outputs.

The runner writes a run manifest (run_manifest.json) recording the seed,
selected horizons/scenarios, split boundaries, model configuration,
Python and dependency versions, date/time, output location, and
completion status, and it refuses to overwrite a non-empty output
directory unless --overwrite is given.

Shipment totals: the simulator's shipment log records transfers across
multiple legs of the network. Total recorded shipment units are a
throughput measure, NOT customer demand fulfilled, and fewer shipments
are NOT automatically better inventory performance.

Run:
    python thesis_short_horizon_experiments.py --output-dir thesis_short_runs

Dependencies: numpy, pandas, scikit-learn, statsmodels, lightgbm.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from statsmodels.tsa.holtwinters import ExponentialSmoothing
import lightgbm as lgb

from Supplychaingeo_item50_v2 import build_example_simulation_extended

SEED = 2025
HORIZON = 7
PIPELINE_MULTIPLIER = 7.0
MODELS = ("Seasonal Naive", "ETS", "LightGBM")
FEATURE_COLS = [
    "lag_1", "lag_7", "lag_14", "lag_28", "rolling_mean_7",
    "rolling_mean_28", "rolling_std_28", "day_of_week", "week_of_year",
]
# Aggregation version for inventory metrics (see module docstring).
# v2 = daily aggregates (sum across items/nodes per day, then mean/max
# across test days). v1 (superseded) used per-row means / single-record
# maxima. The F01 recomputation script uses the same v2 definitions.
INVENTORY_METRICS_VERSION = "inventory-metrics-v2-daily-aggregate"

LGB_PARAMS = {
    "objective": "regression", "n_estimators": 300, "learning_rate": 0.05,
    "num_leaves": 31, "max_depth": -1, "subsample": 0.8,
    "colsample_bytree": 0.8, "random_state": SEED, "verbosity": -1,
}
# LightGBM subsampling audit (do NOT "fix" by adding subsample_freq - that
# would change the experiment):
# - subsample (= bagging_fraction) = 0.8 is INERT here because
#   subsample_freq (= bagging_freq) is unset and defaults to 0, and
#   LightGBM disables bagging when bagging_freq == 0 ("to enable bagging,
#   bagging_freq should be set to a non zero value as well",
#   LightGBM Parameters documentation). No row subsampling occurs.
# - colsample_bytree (= feature_fraction) = 0.8 IS active: LightGBM
#   selects a random 80% subset of features before training each tree.
# The 7,300-day notebook's LightGBM sets neither parameter, so it uses
# no feature subsampling (feature_fraction = 1.0) and no bagging. The
# runner and the notebook therefore differ in LightGBM feature
# subsampling (0.8 vs 1.0); this is a documented protocol difference,
# not a corrected bug. Any protocol with bagging enabled must be
# identified as a separate variant, never substituted into the
# historical one.

# Direction-oriented rank convention for the runner's inventory
# metrics. ONLY the six primary metrics defined by the thesis
# (Section 4.4 and Appendix B) are ranked: fill rate (higher is
# better) and five lower-is-better measures. The other recorded
# measures - maximum destination inventory, maximum total network
# inventory, final destination backlog, and total shipment units -
# are retained as DESCRIPTIVE outcomes and are NOT ranked: the
# thesis states they are not assigned a model ranking because a
# unique optimisation direction is not specified for them, and
# shipment volume alone does not define better or worse
# performance. "Lower" = rank 1 is the smallest value;
# "higher" = rank 1 is the largest value. The direction is a
# numerical convention for ranking, NOT a claim that the value is
# desirable: lower inventory is not automatically better without
# an explicit cost or service objective. No composite score is
# constructed.
INVENTORY_RANK_DIRECTIONS = {
    "total_unfilled_demand": "lower",
    "average_destination_inventory": "lower",
    "average_destination_backlog": "lower",
    "maximum_destination_backlog": "lower",
    "average_total_network_inventory": "lower",
    "fill_rate": "higher",
}
HORIZONS = {
    2000: {"TRAIN_END": 999, "VALIDATION_END": 1499, "TEST_START": 1500, "TEST_END": 1999},
    3000: {"TRAIN_END": 1499, "VALIDATION_END": 2249, "TEST_START": 2250, "TEST_END": 2999},
    5000: {"TRAIN_END": 2999, "VALIDATION_END": 3999, "TEST_START": 4000, "TEST_END": 4999},
}

SCENARIOS = {
    "normal": {
        "demand": {"phi_lo": 0.9990, "phi_hi": 0.9996, "shock_count_scale": 1.0,
                   "shock_height_scale": 1.0, "seasonal_scale": 1.0,
                   "burst_rate_scale": 1.0, "burst_height_scale": 1.0,
                   "base_lambda_lo": 80, "base_lambda_hi": 250},
        "supply_p_onset": 0.0, "supply_length": 0,
    },
    "demand_disruption": {
        "demand": {"phi_lo": 0.9990, "phi_hi": 0.9996, "shock_count_scale": 2.0,
                   "shock_height_scale": 2.0, "seasonal_scale": 1.0,
                   "burst_rate_scale": 1.0, "burst_height_scale": 1.0,
                   "base_lambda_lo": 80, "base_lambda_hi": 250},
        "supply_p_onset": 0.0, "supply_length": 0,
    },
    "supply_disruption": {
        "demand": {"phi_lo": 0.9990, "phi_hi": 0.9996, "shock_count_scale": 1.0,
                   "shock_height_scale": 1.0, "seasonal_scale": 1.0,
                   "burst_rate_scale": 1.0, "burst_height_scale": 1.0,
                   "base_lambda_lo": 80, "base_lambda_hi": 250},
        "supply_p_onset": 0.001, "supply_length": 30,
    },
    "combined_disruption": {
        "demand": {"phi_lo": 0.9990, "phi_hi": 0.9996, "shock_count_scale": 2.0,
                   "shock_height_scale": 2.0, "seasonal_scale": 1.0,
                   "burst_rate_scale": 1.0, "burst_height_scale": 1.0,
                   "base_lambda_lo": 80, "base_lambda_hi": 250},
        "supply_p_onset": 0.001, "supply_length": 30,
    },
}


def make_demand_matrix(sim, items: Dict, days: int) -> pd.DataFrame:
    """Freeze the scenario's stochastic demand once so all models see identical demand."""
    rows = []
    for day in range(days):
        demand = sim.demand_fn(day)
        for item in sorted(items):
            rows.append((day, item, int(demand.get(item, 0))))
    return pd.DataFrame(rows, columns=["day", "item", "demand"])


def item_series_map(demand_df: pd.DataFrame) -> Dict[str, pd.Series]:
    return {
        item: part.set_index("day")["demand"].sort_index().astype(float)
        for item, part in demand_df.groupby("item", sort=True)
    }


def fit_and_forecast(demand_df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Rolling 7-day test forecasts following the notebook's final forecasting cell."""
    test_start, test_end = cfg["TEST_START"], cfg["TEST_END"]
    final_train_end = cfg["VALIDATION_END"]
    series_map = item_series_map(demand_df)
    rows = []

    for item, series in series_map.items():
        training = series.loc[:final_train_end]
        # Seasonal Naive: same weekday from the preceding week at each day.
        for origin in range(test_start, test_end + 1, HORIZON):
            block_end = min(origin + HORIZON - 1, test_end)
            for day in range(origin, block_end + 1):
                rows.append(("Seasonal Naive", item, day,
                             float(series.loc[day - 7]), float(series.loc[day])))

        # ETS level: refit on observations available at each weekly origin.
        history = training.copy()
        for origin in range(test_start, test_end + 1, HORIZON):
            block_end = min(origin + HORIZON - 1, test_end)
            days = np.arange(origin, block_end + 1)
            fit = ExponentialSmoothing(history, trend=None, seasonal=None).fit(optimized=True)
            forecasts = np.asarray(fit.forecast(len(days)), dtype=float)
            for day, forecast in zip(days, forecasts):
                rows.append(("ETS", item, int(day), float(forecast), float(series.loc[day])))
            history = series.loc[:int(days[-1])]

        # LightGBM: fit on pre-test data; recursive predictions within each 7-day block.
        train_values = training.to_numpy(dtype=float)
        g = pd.Series(train_values)
        X = pd.DataFrame({
            "lag_1": g.shift(1), "lag_7": g.shift(7), "lag_14": g.shift(14),
            "lag_28": g.shift(28), "rolling_mean_7": g.shift(1).rolling(7).mean(),
            "rolling_mean_28": g.shift(1).rolling(28).mean(),
            "rolling_std_28": g.shift(1).rolling(28).std(),
        })
        train_days = training.index.to_numpy(dtype=int)
        X["day_of_week"] = train_days % 7
        X["week_of_year"] = (train_days // 7) % 52
        valid = X.notna().all(axis=1)
        model = lgb.LGBMRegressor(**LGB_PARAMS)
        model.fit(X.loc[valid, FEATURE_COLS], train_values[valid.to_numpy()])

        for origin in range(test_start, test_end + 1, HORIZON):
            block_end = min(origin + HORIZON - 1, test_end)
            history_values = list(series.loc[:origin - 1].to_numpy(dtype=float))
            for day in range(origin, block_end + 1):
                h = np.asarray(history_values, dtype=float)
                row = pd.DataFrame([{
                    "lag_1": h[-1], "lag_7": h[-7], "lag_14": h[-14], "lag_28": h[-28],
                    "rolling_mean_7": np.mean(h[-7:]),
                    "rolling_mean_28": np.mean(h[-28:]),
                    "rolling_std_28": np.std(h[-28:], ddof=1),
                    "day_of_week": day % 7, "week_of_year": (day // 7) % 52,
                }])
                forecast = float(model.predict(row[FEATURE_COLS])[0])
                rows.append(("LightGBM", item, day, forecast, float(series.loc[day])))
                history_values.append(forecast)

    return pd.DataFrame(rows, columns=["model", "item", "day", "forecast", "actual"])


def forecast_metrics(forecasts: pd.DataFrame, demand_df: pd.DataFrame, cfg: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    train_end = cfg["VALIDATION_END"]
    series_map = item_series_map(demand_df)
    item_rows = []
    zero_denom_items = []
    for (model, item), part in forecasts.groupby(["model", "item"], sort=False):
        actual = part["actual"].to_numpy(dtype=float)
        pred = part["forecast"].to_numpy(dtype=float)
        train = series_map[item].loc[:train_end].to_numpy(dtype=float)
        denom = float(np.mean(np.abs(train[7:] - train[:-7])))
        if denom <= 0:
            # MASE is undefined when the training series is exactly
            # 7-periodic (zero seasonal-naive scale). Record NaN
            # explicitly and warn; do not substitute a pooled value
            # or silently drop the item.
            zero_denom_items.append((model, item))
            mase = float("nan")
        else:
            mase = float(mean_absolute_error(actual, pred) / denom)
        item_rows.append({
            "model": model, "item": item,
            "MAE": float(mean_absolute_error(actual, pred)),
            "RMSE": float(np.sqrt(mean_squared_error(actual, pred))),
            "MASE": mase,
        })
    if zero_denom_items:
        print(
            "WARNING: MASE undefined (zero training-scale denominator) for "
            f"{zero_denom_items}; recorded as NaN. The F03 alignment "
            "analysis rejects non-finite values."
        )
    item_metrics = pd.DataFrame(item_rows)
    summary_rows = []
    for model, part in item_metrics.groupby("model", sort=False):
        summary = {"model": model}
        for metric in ("MAE", "RMSE", "MASE"):
            summary[f"mean_{metric}"] = float(part[metric].mean())
            summary[f"median_{metric}"] = float(part[metric].median())
        summary_rows.append(summary)
    return item_metrics, pd.DataFrame(summary_rows)


def forecast_target_lookup(forecasts: pd.DataFrame, cfg: dict) -> Dict[Tuple[str, int, str], float]:
    """Map each model/item/day to its forecast sum for the containing 7-day block."""
    lookup = {}
    start, end = cfg["TEST_START"], cfg["TEST_END"]
    for (model, item), part in forecasts.groupby(["model", "item"], sort=False):
        part = part.set_index("day").sort_index()
        for origin in range(start, end + 1, HORIZON):
            block_end = min(origin + HORIZON - 1, end)
            total = float(part.loc[origin:block_end, "forecast"].sum())
            for day in range(origin, block_end + 1):
                lookup[(model, day, item)] = total
    return lookup


def _require_finite(df: pd.DataFrame, columns: list, name: str) -> None:
    for col in columns:
        vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(vals).all():
            raise ValueError(f"{name}: non-finite or non-numeric values in column {col}")


def compute_inventory_metrics(
    test_daily: pd.DataFrame,
    test_inventory: pd.DataFrame,
    test_backlog: pd.DataFrame,
    shipments: pd.DataFrame,
    destination_nodes,
    demand_df: pd.DataFrame,
    test_start: int,
    test_end: int,
) -> dict:
    """Compute test-window inventory metrics from test-window record frames.

    Definitions (aggregation version ``INVENTORY_METRICS_VERSION``):
      - destination inventory: sum of ``on_hand`` across items at
        destination nodes, per day; mean and maximum across test days.
      - destination backlog: sum of ``backlog`` across items at
        destination nodes, per day; mean, maximum, and final (last
        test day) across test days.
      - network inventory: sum of ``on_hand`` across all nodes and
        items, per day; mean and maximum across test days.
      - totals: ``total_test_demand``, ``total_served_from_stock``,
        ``total_unfilled_demand`` summed from the daily records.
      - ``fill_rate = total_served_from_stock / total_test_demand``.
      - ``total_shipment_units_test_window``: sum of shipment units
        whose dispatch day is in the test window. A throughput
        measure, not demand fulfilled.

    Validation (all failures are explicit errors, never silent NaNs):
      - required columns present; no missing or non-finite values in
        numeric columns; shipment units >= 0.
      - exact coverage: one row per (day, item) in daily records and
        one row per (day, node, item) in inventory/backlog records,
        for every day in the test window; item sets equal the frozen
        demand item set; no extra days/items; the node set is
        identical for every (day, item).
      - per-row identity on daily records: served + unfilled == demand.
      - frozen-demand consistency: daily demand equals the frozen
        demand for every (day, item), and the test-window total
        equals the frozen-demand test-window total.
      - aggregate identity: served + unfilled == test demand (within
        1e-9 relative) and fill_rate == served / test demand.
    """
    n_days = test_end - test_start + 1
    if n_days <= 0:
        raise ValueError(f"invalid test window [{test_start}, {test_end}]")
    expected_days = set(range(test_start, test_end + 1))
    _require_columns(test_daily, ["day", "item", "demand", "served_from_stock", "new_backlog_today"], "daily_records")
    _require_columns(test_inventory, ["day", "node", "item", "on_hand"], "inventory_history")
    _require_columns(test_backlog, ["day", "node", "item", "backlog"], "backlog_history")
    _require_columns(shipments, ["day", "units"], "shipments")
    _require_columns(demand_df, ["day", "item", "demand"], "frozen demand")
    for df, cols, name in (
        (test_daily, ["day", "item", "demand", "served_from_stock", "new_backlog_today"], "daily_records"),
        (test_inventory, ["day", "node", "item", "on_hand"], "inventory_history"),
        (test_backlog, ["day", "node", "item", "backlog"], "backlog_history"),
        (shipments, ["day", "units"], "shipments"),
    ):
        if df[cols].isna().any().any():
            raise ValueError(f"{name}: missing values in required columns")
    _require_finite(test_daily, ["demand", "served_from_stock", "new_backlog_today"], "daily_records")
    _require_finite(test_inventory, ["on_hand"], "inventory_history")
    _require_finite(test_backlog, ["backlog"], "backlog_history")
    _require_finite(shipments, ["units"], "shipments")
    if len(shipments) and (shipments["units"] < 0).any():
        raise ValueError("shipments: negative shipment units")

    frozen_test = demand_df[(demand_df["day"] >= test_start) & (demand_df["day"] <= test_end)]
    frozen_items = set(frozen_test["item"].unique().tolist())
    if not frozen_items:
        raise ValueError("frozen demand: no rows in the test window")

    # Exact coverage: daily records.
    daily_keys = set(zip(test_daily["day"].tolist(), test_daily["item"].tolist()))
    expected_daily = {(d, it) for d in expected_days for it in frozen_items}
    if len(test_daily) != len(daily_keys):
        raise ValueError("daily_records: duplicate (day, item) rows")
    if daily_keys != expected_daily:
        raise ValueError(
            "daily_records: coverage != test window x frozen item set; "
            f"missing={sorted(expected_daily - daily_keys)[:5]}, extra={sorted(daily_keys - expected_daily)[:5]}"
        )

    # Exact coverage: inventory / backlog records (Cartesian product of
    # test days x observed nodes x frozen items; node set identical per
    # (day, item)).
    for df, name in ((test_inventory, "inventory_history"), (test_backlog, "backlog_history")):
        keys = set(zip(df["day"].tolist(), df["node"].tolist(), df["item"].tolist()))
        if len(df) != len(keys):
            raise ValueError(f"{name}: duplicate (day, node, item) rows")
        nodes = set(df["node"].unique().tolist())
        expected = {(d, n, it) for d in expected_days for n in nodes for it in frozen_items}
        if keys != expected:
            raise ValueError(
                f"{name}: coverage != test window x nodes x frozen item set; "
                f"missing={sorted(expected - keys)[:5]}, extra={sorted(keys - expected)[:5]}"
            )
        node_sets = {tuple(sorted(set(g["node"].tolist()))) for _, g in df.groupby(["day", "item"])}
        if len(node_sets) != 1:
            raise ValueError(f"{name}: node set differs across (day, item) groups")

    # Per-row identity on daily records: served + unfilled == demand.
    row_gap = (test_daily["served_from_stock"] + test_daily["new_backlog_today"] - test_daily["demand"]).abs().max()
    if row_gap > 1e-9:
        raise ValueError(f"daily_records: per-row served + unfilled != demand (max gap {row_gap})")

    # Frozen-demand consistency per (day, item).
    merged = test_daily.merge(frozen_test[["day", "item", "demand"]], on=["day", "item"], suffixes=("", "_frozen"))
    if (merged["demand"] != merged["demand_frozen"]).any():
        first = merged[merged["demand"] != merged["demand_frozen"]].iloc[0]
        raise ValueError(
            f"daily_records: demand != frozen demand at day={first['day']}, item={first['item']}: "
            f"{first['demand']} vs {first['demand_frozen']}"
        )

    total_test_demand = float(test_daily["demand"].sum())
    total_served = float(test_daily["served_from_stock"].sum())
    total_unfilled = float(test_daily["new_backlog_today"].sum())
    frozen_test_demand = float(frozen_test["demand"].sum())
    if total_test_demand <= 0:
        raise ValueError("test-window demand is not positive; fill rate undefined")
    if abs(total_test_demand - frozen_test_demand) > 1e-6:
        raise ValueError(
            f"daily_records test demand {total_test_demand} != frozen-demand test total {frozen_test_demand}"
        )
    if abs((total_served + total_unfilled) - total_test_demand) > 1e-9 * max(1.0, total_test_demand):
        raise ValueError(
            f"fill-rate identity failed: served + unfilled = {total_served + total_unfilled} "
            f"!= test demand {total_test_demand}"
        )
    fill_rate = total_served / total_test_demand
    if abs(fill_rate - (1.0 - total_unfilled / total_test_demand)) > 1e-9:
        raise ValueError("fill-rate identity failed: fill_rate != 1 - unfilled / test demand")

    # Daily aggregates (sum across items/nodes per day, then mean/max).
    dest_inv = test_inventory[test_inventory["node"].isin(destination_nodes)]
    dest_backlog = test_backlog[test_backlog["node"].isin(destination_nodes)]
    if dest_inv.empty or dest_backlog.empty:
        raise ValueError("no destination-node rows in inventory/backlog records")
    dest_daily = dest_inv.groupby("day")["on_hand"].sum()
    network_daily = test_inventory.groupby("day")["on_hand"].sum()
    backlog_daily = dest_backlog.groupby("day")["backlog"].sum()
    for series, name in ((dest_daily, "destination inventory"), (network_daily, "network inventory"), (backlog_daily, "destination backlog")):
        if set(series.index.tolist()) != expected_days:
            raise ValueError(f"{name}: daily series does not cover every test day")

    test_ship = shipments[(shipments["day"] >= test_start) & (shipments["day"] <= test_end)]
    return {
        "test_start": test_start,
        "test_end": test_end,
        "total_test_demand": total_test_demand,
        "total_served_from_stock": total_served,
        "total_unfilled_demand": total_unfilled,
        "fill_rate": fill_rate,
        "average_destination_inventory": float(dest_daily.mean()),
        "maximum_destination_inventory": float(dest_daily.max()),
        "average_total_network_inventory": float(network_daily.mean()),
        "maximum_total_network_inventory": float(network_daily.max()),
        "average_destination_backlog": float(backlog_daily.mean()),
        "maximum_destination_backlog": float(backlog_daily.max()),
        "final_destination_backlog": float(backlog_daily.loc[test_end]),
        "total_shipment_units_test_window": float(test_ship["units"].sum()),
        "aggregation_version": INVENTORY_METRICS_VERSION,
    }


def _require_columns(df: pd.DataFrame, required: list, name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing required columns: {missing}")


def build_run_manifest(output_dir, horizons, scenarios, status, started_at=None, completed_at=None) -> dict:
    """Run manifest: seed, config, versions, timing, output, status."""
    def _version(pkg: str) -> str:
        try:
            return importlib.metadata.version(pkg)
        except Exception:
            return "unknown"
    return {
        "script": "thesis_short_horizon_experiments.py",
        "command": sys.argv,
        "status": status,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "seed": SEED,
        "horizons": {str(h): HORIZONS[h] for h in horizons},
        "scenarios": list(scenarios),
        "forecast_horizon_days": HORIZON,
        "pipeline_multiplier": PIPELINE_MULTIPLIER,
        "models": list(MODELS),
        "lightgbm_params": dict(LGB_PARAMS),
        "feature_columns": list(FEATURE_COLS),
        "inventory_metrics_version": INVENTORY_METRICS_VERSION,
        "python_version": sys.version,
        "dependency_versions": {
            pkg: _version(pkg) for pkg in ("numpy", "pandas", "scikit-learn", "statsmodels", "lightgbm")
        },
        "output_dir": str(output_dir),
    }


def check_output_dir(output_dir: Path, overwrite: bool) -> None:
    """Refuse to use a non-empty output directory unless overwrite is set."""
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise SystemExit(
            f"output directory {output_dir} is not empty; pass --overwrite to overwrite it"
        )


def validate_forecast_coverage(all_forecasts, horizons) -> None:
    """Validate forecast coverage before aggregate results are saved.

    Every (horizon, scenario, model, item) must have exactly one row
    per day of its horizon's test window; duplicates, missing days,
    extra days, and non-finite forecast/actual values are rejected.
    """
    if not all_forecasts:
        raise ValueError("no forecasts to validate")
    df = pd.concat(all_forecasts, ignore_index=True)
    _require_columns(df, ["horizon_days", "scenario", "model", "item", "day"], "forecasts")
    if df[["horizon_days", "scenario", "model", "item", "day"]].isna().any().any():
        raise ValueError("forecasts: missing values in key columns")
    if df.duplicated(subset=["horizon_days", "scenario", "model", "item", "day"]).any():
        raise ValueError("forecasts: duplicate (horizon, scenario, model, item, day) rows")
    for col in ("forecast", "actual"):
        if col in df.columns:
            _require_finite(df, [col], "forecasts")
    for (horizon, scenario, model, item), grp in df.groupby(["horizon_days", "scenario", "model", "item"]):
        cfg = HORIZONS.get(int(horizon))
        if cfg is None:
            raise ValueError(f"forecasts: unknown horizon {horizon}")
        expected = set(range(cfg["TEST_START"], cfg["TEST_END"] + 1))
        days = set(grp["day"].tolist())
        if days != expected:
            raise ValueError(
                f"forecasts: incomplete day coverage for ({horizon}, {scenario}, {model}, {item}): "
                f"missing={sorted(expected - days)[:5]}, extra={sorted(days - expected)[:5]}"
            )


def validate_inventory_outcomes(inventory_df: pd.DataFrame) -> None:
    """Validate the aggregate inventory outcomes before they are saved.

    Checks the output schema (required columns, no missing/non-finite
    values), the per-row service identities, the aggregation version,
    and that all models within a (horizon, scenario) group share the
    same frozen test-demand total.
    """
    required = [
        "horizon_days", "scenario", "model", "test_start", "test_end",
        "total_test_demand", "total_served_from_stock", "total_unfilled_demand",
        "fill_rate", "average_destination_inventory", "maximum_destination_inventory",
        "average_total_network_inventory", "maximum_total_network_inventory",
        "average_destination_backlog", "maximum_destination_backlog",
        "final_destination_backlog", "total_shipment_units_test_window",
        "aggregation_version",
    ]
    _require_columns(inventory_df, required, "inventory outcomes")
    if inventory_df[required].isna().any().any():
        raise ValueError("inventory outcomes: missing values in required columns")
    numeric = [c for c in required if c not in ("scenario", "model", "aggregation_version")]
    _require_finite(inventory_df, numeric, "inventory outcomes")
    if (inventory_df["aggregation_version"] != INVENTORY_METRICS_VERSION).any():
        raise ValueError("inventory outcomes: aggregation_version mismatch")
    for _, row in inventory_df.iterrows():
        if row["total_test_demand"] <= 0:
            raise ValueError(f"inventory outcomes: non-positive test demand at {row['horizon_days']}/{row['scenario']}/{row['model']}")
        if abs((row["total_served_from_stock"] + row["total_unfilled_demand"]) - row["total_test_demand"]) > 1e-9 * max(1.0, row["total_test_demand"]):
            raise ValueError(f"inventory outcomes: served + unfilled != test demand at {row['horizon_days']}/{row['scenario']}/{row['model']}")
        if abs(row["fill_rate"] - row["total_served_from_stock"] / row["total_test_demand"]) > 1e-9:
            raise ValueError(f"inventory outcomes: fill_rate != served / test demand at {row['horizon_days']}/{row['scenario']}/{row['model']}")
    for (horizon, scenario), grp in inventory_df.groupby(["horizon_days", "scenario"]):
        if grp["total_test_demand"].nunique() != 1:
            raise ValueError(
                f"inventory outcomes: models in ({horizon}, {scenario}) do not share "
                f"the same frozen test-demand total: {grp[['model', 'total_test_demand']].to_dict('records')}"
            )


def run_inventory(scenario_name: str, scenario_cfg: dict, demand_df: pd.DataFrame,
                  days: int, cfg: dict, model_name: str, forecast_lookup: dict,
                  output_dir: Path) -> dict:
    """Run one model's inventory policy using the forecast sum for each test block."""
    run_dir = output_dir / str(days) / scenario_name / model_name.lower().replace(" ", "_")
    run_dir.mkdir(parents=True, exist_ok=True)
    sim, net, items, _ = build_example_simulation_extended(
        seed=SEED, horizon_days=days, pipeline_multiplier=PIPELINE_MULTIPLIER,
        streaming_out_dir=str(run_dir), packing="greedy", scenario=dict(scenario_cfg["demand"]),
        disruption_p_onset=scenario_cfg["supply_p_onset"],
        disruption_length_days=scenario_cfg["supply_length"],
    )
    demand_lookup = {(int(r.day), str(r.item)): int(r.demand) for r in demand_df.itertuples(index=False)}
    sim.demand_fn = lambda day: {iid: demand_lookup[(day, iid)] for iid in items}
    original_step = sim.step
    test_start, test_end = cfg["TEST_START"], cfg["TEST_END"]
    alpha = sim.ema_alpha

    def forecast_controlled_step(day: int):
        if test_start <= day <= test_end:
            for iid in items:
                block_sum = forecast_lookup[(model_name, day, iid)]
                desired_post_update_ema = block_sum / PIPELINE_MULTIPLIER
                actual_demand = demand_lookup[(day, iid)]
                # Compensate for the simulator's native EMA update so that
                # pipeline_multiplier * post-update EMA equals the 7-day forecast sum.
                sim.demand_ema[iid] = (
                    desired_post_update_ema - alpha * actual_demand
                ) / (1.0 - alpha)
        original_step(day)

    sim.step = forecast_controlled_step
    print(f"    Inventory: {scenario_name} | {days} days | {model_name}")
    sim.run()

    # Read only the test-window rows from streamed files to avoid retaining
    # multi-million-row inventory/backlog histories in memory.
    def read_test_window(csv_path: Path) -> pd.DataFrame:
        pieces = []
        for chunk in pd.read_csv(csv_path, chunksize=250_000):
            keep = chunk[(chunk["day"] >= test_start) & (chunk["day"] <= test_end)]
            if not keep.empty:
                pieces.append(keep)
        return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()

    test_daily = read_test_window(run_dir / "daily_records.csv")
    test_inventory = read_test_window(run_dir / "inventory_history.csv")
    test_backlog = read_test_window(run_dir / "backlog_history.csv")
    shipment_path = run_dir / "shipments.csv"
    shipments = pd.read_csv(shipment_path)
    destinations = {nid for nid, node in net.nodes.items() if node.is_destination}
    metric = compute_inventory_metrics(
        test_daily, test_inventory, test_backlog, shipments,
        destinations, demand_df, test_start, test_end,
    )
    metric = {
        "horizon_days": days, "scenario": scenario_name, "model": model_name,
        **metric,
    }
    # Save raw model/scenario inventory traces separately to keep the experiment auditable.
    test_daily.to_csv(run_dir / "test_daily_records.csv", index=False)
    test_inventory.to_csv(run_dir / "test_inventory_history.csv", index=False)
    test_backlog.to_csv(run_dir / "test_backlog_history.csv", index=False)
    shipments.to_csv(run_dir / "shipments.csv", index=False)
    return metric


def rank_inventory_metrics(inventory_df: pd.DataFrame) -> pd.DataFrame:
    """Rank each inventory metric separately per (horizon, scenario).

    Ranking is metric-specific: rank 1 is the best rank under the
    metric's documented numerical direction (see
    INVENTORY_RANK_DIRECTIONS), average tie method. No aggregate
    score is calculated. Returns one row per
    (horizon, scenario, metric, model) with value and rank.
    """
    rank_rows = []
    for keys, group in inventory_df.groupby(["horizon_days", "scenario"], sort=False):
        for metric, direction in INVENTORY_RANK_DIRECTIONS.items():
            ranks = group[metric].rank(method="average", ascending=(direction == "lower"))
            for _, row in group.iterrows():
                rank_rows.append({"horizon_days": keys[0], "scenario": keys[1], "metric": metric,
                                  "model": row["model"], "value": row[metric],
                                  "rank": float(ranks.loc[row.name])})
    return pd.DataFrame(rank_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="thesis_short_runs")
    parser.add_argument("--horizons", nargs="+", type=int, choices=sorted(HORIZONS), default=[2000, 3000, 5000])
    parser.add_argument("--scenarios", nargs="+", choices=sorted(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument("--overwrite", action="store_true", help="allow using a non-empty output directory")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    check_output_dir(output_dir, args.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    (output_dir / "run_manifest.json").write_text(json.dumps(
        build_run_manifest(output_dir, args.horizons, args.scenarios, "started", started_at=started_at),
        indent=2,
    ))
    all_forecast_summary, all_item_metrics, all_forecasts, all_inventory = [], [], [], []

    random.seed(SEED)
    np.random.seed(SEED)
    for days in args.horizons:
        cfg = {"RUN_DAYS": days, **HORIZONS[days], "HORIZON": HORIZON}
        print("\n" + "=" * 84)
        print(f"HORIZON={days} | train 0-{cfg['TRAIN_END']} | validation {cfg['TRAIN_END']+1}-{cfg['VALIDATION_END']} | test {cfg['TEST_START']}-{cfg['TEST_END']}")
        (output_dir / str(days)).mkdir(parents=True, exist_ok=True)
        (output_dir / str(days) / "split_config.json").write_text(json.dumps(cfg, indent=2))

        for scenario_name in args.scenarios:
            scenario_cfg = SCENARIOS[scenario_name]
            print(f"\n--- {days} days | {scenario_name} ---")
            # Build demand once; use the exact same realized demand for all forecast models
            # and all three inventory-policy comparisons in this scenario/horizon.
            demand_sim, _, demand_items, demand_signals = build_example_simulation_extended(
                seed=SEED, horizon_days=days, pipeline_multiplier=PIPELINE_MULTIPLIER,
                streaming_out_dir=None, packing="greedy", scenario=dict(scenario_cfg["demand"]),
                disruption_p_onset=scenario_cfg["supply_p_onset"],
                disruption_length_days=scenario_cfg["supply_length"],
            )
            demand_df = make_demand_matrix(demand_sim, demand_items, days)
            demand_dir = output_dir / str(days) / scenario_name
            demand_dir.mkdir(parents=True, exist_ok=True)
            demand_df.to_csv(demand_dir / "frozen_demand.csv", index=False)
            np.save(demand_dir / "demand_signals.npy", demand_signals)

            forecasts = fit_and_forecast(demand_df, cfg)
            forecasts.insert(0, "scenario", scenario_name)
            forecasts.insert(0, "horizon_days", days)
            forecasts.to_csv(demand_dir / "test_forecasts.csv", index=False)
            raw_for_metric = forecasts[["model", "item", "day", "forecast", "actual"]]
            item_metrics, summary_metrics = forecast_metrics(raw_for_metric, demand_df, cfg)
            item_metrics.insert(0, "scenario", scenario_name)
            item_metrics.insert(0, "horizon_days", days)
            summary_metrics.insert(0, "scenario", scenario_name)
            summary_metrics.insert(0, "horizon_days", days)
            item_metrics.to_csv(demand_dir / "forecast_item_metrics.csv", index=False)
            summary_metrics.to_csv(demand_dir / "forecast_summary_metrics.csv", index=False)
            all_forecasts.append(forecasts)
            all_item_metrics.append(item_metrics)
            all_forecast_summary.append(summary_metrics)

            lookup = forecast_target_lookup(raw_for_metric, cfg)
            before = len(all_inventory)
            for model_name in MODELS:
                result = run_inventory(scenario_name, scenario_cfg, demand_df, days, cfg,
                                       model_name, lookup, output_dir)
                all_inventory.append(result)
            # All three model runs in this horizon/scenario must use the
            # same frozen demand: their test-demand totals must agree
            # with each other and with the frozen-demand test total.
            scenario_results = all_inventory[before:]
            frozen_test_total = float(
                demand_df[(demand_df["day"] >= cfg["TEST_START"]) & (demand_df["day"] <= cfg["TEST_END"])]["demand"].sum()
            )
            for result in scenario_results:
                if abs(result["total_test_demand"] - frozen_test_total) > 1e-6:
                    raise ValueError(
                        f"{days}/{scenario_name}/{result['model']}: test demand "
                        f"{result['total_test_demand']} != frozen-demand test total {frozen_test_total}"
                    )

    # Validate forecast coverage and the inventory-outcome schema BEFORE
    # saving aggregate results, so a bad run never produces apparently
    # valid summary statistics.
    validate_forecast_coverage(all_forecasts, args.horizons)
    inventory_df = pd.DataFrame(all_inventory)
    validate_inventory_outcomes(inventory_df)

    pd.concat(all_forecasts, ignore_index=True).to_csv(output_dir / "all_test_forecasts.csv", index=False)
    pd.concat(all_item_metrics, ignore_index=True).to_csv(output_dir / "all_forecast_item_metrics.csv", index=False)
    pd.concat(all_forecast_summary, ignore_index=True).to_csv(output_dir / "all_forecast_summary_metrics.csv", index=False)
    inventory_df.to_csv(output_dir / "all_inventory_outcomes.csv", index=False)

    # Ranking is metric-specific. No aggregate score is calculated.
    rank_rows = rank_inventory_metrics(inventory_df)
    rank_rows.to_csv(output_dir / "inventory_metric_rankings.csv", index=False)
    completed_at = datetime.now(timezone.utc).isoformat()
    (output_dir / "run_manifest.json").write_text(json.dumps(
        build_run_manifest(output_dir, args.horizons, args.scenarios, "completed",
                           started_at=started_at, completed_at=completed_at),
        indent=2,
    ))
    print("\nFinished. Outputs written to:", output_dir)
    print("No full run is performed by creating this file; results are produced when you execute it.")


if __name__ == "__main__":
    main()
