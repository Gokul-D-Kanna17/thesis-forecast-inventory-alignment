"""Short-horizon thesis experiments: forecast accuracy vs inventory decisions.

Runs 2,000-, 3,000-, and 5,000-day simulations for Normal, Demand Disruption,
Supply Disruption, and Combined Disruption. Uses the supplied simulator modules
in the same directory as this script.

Forecast models: Seasonal Naive, ETS level, LightGBM.
Forecast horizon: 7 days. No composite score or overall model winner is made.

Run:
    python thesis_short_horizon_experiments.py --output-dir thesis_short_runs

Dependencies: numpy, pandas, scikit-learn, statsmodels, lightgbm.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
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
LGB_PARAMS = {
    "objective": "regression", "n_estimators": 300, "learning_rate": 0.05,
    "num_leaves": 31, "max_depth": -1, "subsample": 0.8,
    "colsample_bytree": 0.8, "random_state": SEED, "verbosity": -1,
}

# Boundaries are inclusive. TEST_START is VALIDATION_END + 1.
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
    for (model, item), part in forecasts.groupby(["model", "item"], sort=False):
        actual = part["actual"].to_numpy(dtype=float)
        pred = part["forecast"].to_numpy(dtype=float)
        train = series_map[item].loc[:train_end].to_numpy(dtype=float)
        denom = float(np.mean(np.abs(train[7:] - train[:-7])))
        item_rows.append({
            "model": model, "item": item,
            "MAE": float(mean_absolute_error(actual, pred)),
            "RMSE": float(np.sqrt(mean_squared_error(actual, pred))),
            "MASE": float(mean_absolute_error(actual, pred) / denom) if denom > 0 else np.nan,
        })
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
    dest_inv = test_inventory[test_inventory["node"].isin(destinations)]
    dest_backlog = test_backlog[test_backlog["node"].isin(destinations)]

    total_demand = float(test_daily["demand"].sum())
    served = float(test_daily["served_from_stock"].sum())
    new_unfilled = float(test_daily["new_backlog_today"].sum())
    metric = {
        "horizon_days": days, "scenario": scenario_name, "model": model_name,
        "test_start": test_start, "test_end": test_end,
        "fill_rate": served / total_demand if total_demand else np.nan,
        "total_unfilled_demand": new_unfilled,
        "average_destination_inventory": float(dest_inv["on_hand"].mean()) if len(dest_inv) else np.nan,
        "average_destination_backlog": float(dest_backlog["backlog"].mean()) if len(dest_backlog) else np.nan,
        "maximum_destination_backlog": float(dest_backlog["backlog"].max()) if len(dest_backlog) else np.nan,
        "average_total_network_inventory": float(test_inventory["on_hand"].mean()) if len(test_inventory) else np.nan,
        "maximum_destination_inventory": float(dest_inv["on_hand"].max()) if len(dest_inv) else np.nan,
        "maximum_total_network_inventory": float(test_inventory["on_hand"].max()) if len(test_inventory) else np.nan,
        "final_destination_backlog": float(dest_backlog[dest_backlog["day"] == test_end]["backlog"].sum()),
        "total_shipment_units_test_window": float(shipments[(shipments["day"] >= test_start) & (shipments["day"] <= test_end)]["units"].sum()) if len(shipments) else 0.0,
    }
    # Save raw model/scenario inventory traces separately to keep the experiment auditable.
    test_daily.to_csv(run_dir / "test_daily_records.csv", index=False)
    test_inventory.to_csv(run_dir / "test_inventory_history.csv", index=False)
    test_backlog.to_csv(run_dir / "test_backlog_history.csv", index=False)
    shipments.to_csv(run_dir / "shipments.csv", index=False)
    return metric


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="thesis_short_runs")
    parser.add_argument("--horizons", nargs="+", type=int, choices=sorted(HORIZONS), default=[2000, 3000, 5000])
    parser.add_argument("--scenarios", nargs="+", choices=sorted(SCENARIOS), default=list(SCENARIOS))
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
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
            for model_name in MODELS:
                result = run_inventory(scenario_name, scenario_cfg, demand_df, days, cfg,
                                       model_name, lookup, output_dir)
                all_inventory.append(result)

    pd.concat(all_forecasts, ignore_index=True).to_csv(output_dir / "all_test_forecasts.csv", index=False)
    pd.concat(all_item_metrics, ignore_index=True).to_csv(output_dir / "all_forecast_item_metrics.csv", index=False)
    pd.concat(all_forecast_summary, ignore_index=True).to_csv(output_dir / "all_forecast_summary_metrics.csv", index=False)
    inventory_df = pd.DataFrame(all_inventory)
    inventory_df.to_csv(output_dir / "all_inventory_outcomes.csv", index=False)

    # Ranking is metric-specific. No aggregate score is calculated.
    lower_better = ["total_unfilled_demand", "average_destination_inventory",
                    "average_destination_backlog", "maximum_destination_backlog",
                    "average_total_network_inventory", "maximum_destination_inventory",
                    "maximum_total_network_inventory", "final_destination_backlog",
                    "total_shipment_units_test_window"]
    higher_better = ["fill_rate"]
    rank_rows = []
    for keys, group in inventory_df.groupby(["horizon_days", "scenario"], sort=False):
        for metric in lower_better:
            for _, row in group.iterrows():
                rank_rows.append({"horizon_days": keys[0], "scenario": keys[1], "metric": metric,
                                  "model": row["model"], "value": row[metric],
                                  "rank": float(group[metric].rank(method="average", ascending=True).loc[row.name])})
        for metric in higher_better:
            for _, row in group.iterrows():
                rank_rows.append({"horizon_days": keys[0], "scenario": keys[1], "metric": metric,
                                  "model": row["model"], "value": row[metric],
                                  "rank": float(group[metric].rank(method="average", ascending=False).loc[row.name])})
    pd.DataFrame(rank_rows).to_csv(output_dir / "inventory_metric_rankings.csv", index=False)
    print("\nFinished. Outputs written to:", output_dir)
    print("No full run is performed by creating this file; results are produced when you execute it.")


if __name__ == "__main__":
    main()
