"""F01 - Inventory-window recomputation from frozen source CSVs.

Recomputes inventory outcomes for all scenarios and models over ONE
common test window (default days 6200-7299 inclusive) from the underlying
per-model records. Applies the same window and the same definitions to
Normal, Demand Disruption, Supply Disruption, and Combined Disruption.

Inputs (via a JSON manifest; no layout is assumed):
  manifest = {"scenarios": [{"scenario": <name>,
                             "demand_file": <frozen demand CSV>,
                             "forecast_file": <optional forecast CSV>,
                             "models": [{"model": <name>,
                                         "inventory_dir": <dir>}, ...]}, ...]}
  Each inventory_dir must contain daily_records.csv, inventory_history.csv,
  backlog_history.csv, shipments.csv (simulator schema).
  demand_file is the frozen demand CSV (day, item, demand).
  forecast_file, if given, is used ONLY to cross-check test demand
  (its actuals summed over the test window must equal inventory test demand).

Definitions (all test-window metrics use days test_start..test_end):
  Aggregation version: inventory-metrics-v2-daily-aggregate (same
  version as the short-horizon runner). Inventory and backlog levels
  are DAILY AGGREGATES: each day's value is the sum across items (and
  across nodes for network inventory); the mean and maximum are taken
  across test days. This matches the 7,300-day notebook's aggregation
  (groupby day, sum, then mean/max). Earlier versions of this script
  used per-row (day, item) means and single-record maxima; those are
  different quantities and must not be compared to daily aggregates.
  test_demand      = sum(demand) in daily_records over the test window
                     (must equal frozen-demand test sum).
  test_served      = sum(served_from_stock) over the test window.
  fill_rate        = test_served / test_demand.
  total_unfilled   = sum(new_backlog_today) over the test window.
  Identity (same window/population): fill_rate = 1 - total_unfilled /
  test_demand. Verified per row-group; failure is an error, because the
  simulator guarantees served + unfilled = demand per (day, item).
  average_destination_inventory  = mean over test days of the daily
                     destination total (sum of inventory_history
                     on_hand across items at the destination node),
                     end-of-day snapshots.
  maximum_destination_inventory  = max over test days of the same
                     daily destination total.
  average_total_network_inventory = mean over test days of the daily
                     network total (sum of inventory_history on_hand
                     across all nodes and items).
  maximum_total_network_inventory = max over test days of the same
                     daily network total.
  average_destination_backlog  = mean over test days of the daily
                     destination backlog total (sum of backlog_history
                     backlog across items at the destination node).
  maximum_destination_backlog  = max over test days of the same daily
                     destination backlog total.
  final_destination_backlog    = daily destination backlog total on
                     day test_end (sum across items).
  total_shipment_units_test_window = sum of shipments units where the
                     dispatch day is in the test window. A throughput
                     measure, not demand fulfilled.
  full_horizon_demand = sum of frozen demand over ALL days. Reported as a
                     SEPARATELY LABELLED descriptive total; never used as
                     a denominator or mixed into test-window comparisons.

Validation (all failures are explicit errors):
  - Required files exist; required columns present; no missing values in
    key columns.
  - Files are sorted by their key columns (verified while reading);
    duplicate key rows rejected (adjacent-duplicate check is complete
    only because sortedness is verified first).
  - Daily coverage: for every item, every day in the file's observed
    range is present exactly once (no gaps, no duplicates); the range
    must cover the test window. Frozen demand must cover days
    0..test_end contiguously.
  - Item sets: identical across all models and scenarios and equal to the
    frozen-demand item set.
  - Demand-inventory consistency: inventory daily demand equals frozen
    demand for every (day, item).
  - Optional forecast cross-check: forecast actuals summed over the test
    window equal inventory test demand.

Outputs (output_dir):
  recomputed_inventory_outcomes.csv  (one row per scenario/model)
  recomputed_inventory_metadata.json (inputs with paths, window,
    definitions, validation results, provenance, identity check)

No thesis results are produced from synthetic fixtures. The CLI is for
real frozen data only; unit tests call the functions on synthetic
fixtures and never write thesis outputs.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

TEST_START_DEFAULT = 6200
TEST_END_DEFAULT = 7299
DESTINATION_NODE_DEFAULT = "NewYork"
CHUNKSIZE_DEFAULT = 250_000

DAILY_REQUIRED = [
    "day",
    "item",
    "demand",
    "served_from_stock",
    "new_backlog_today",
    "dest_on_hand_end_before_ship",
    "dest_backlog_end_before_ship",
]
INV_REQUIRED = ["day", "node", "item", "on_hand"]
BACKLOG_REQUIRED = ["day", "node", "item", "backlog"]
SHIP_REQUIRED = ["day", "arrival_day", "from", "to", "item", "units", "path_nodes", "edge_times"]
DEMAND_REQUIRED = ["day", "item", "demand"]

INVENTORY_FILES = ("daily_records.csv", "inventory_history.csv", "backlog_history.csv", "shipments.csv")


def _validate_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing required columns: {missing}")


def _read_validated_chunks(path: Path, required: list[str], sort_cols: list[str],
                           unique_cols: list[str] | None, chunksize: int):
    """Yield chunks of a CSV, verifying columns, sortedness, and duplicates.

    Sortedness is type-aware (numeric day sorts numerically, not
    lexicographically). Duplicates are checked on unique_cols (None
    skips the duplicate check, used for shipments, which have no unique
    key - two identical shipments can be legitimate). Because sortedness
    is verified, a duplicate unique key is necessarily adjacent
    (within-chunk check + boundary check), so the check is complete.
    """
    if not path.exists():
        raise FileNotFoundError(f"required file not found: {path}")
    try:
        header = pd.read_csv(path, nrows=0)
    except Exception as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    _validate_columns(header, required, str(path))
    prev_last_sort_key = None
    prev_last_unique_key = None
    reader = pd.read_csv(path, chunksize=chunksize)
    try:
        for chunk in reader:
            _validate_columns(chunk, required, str(path))
            if chunk[required].isna().any().any():
                raise ValueError(f"{path}: missing values in required columns")
            # Sortedness (type-aware, stable sort preserves file order iff sorted).
            sorted_chunk = chunk.sort_values(sort_cols, kind="mergesort")
            if not sorted_chunk.index.equals(chunk.index):
                raise ValueError(
                    f"{path}: rows are not sorted by {sort_cols}; cannot verify "
                    "completeness/duplicates reliably"
                )
            if unique_cols is not None and bool(chunk.duplicated(subset=unique_cols).any()):
                raise ValueError(f"{path}: duplicate key row on {unique_cols}")
            if len(chunk) > 0:
                first_sort = tuple(chunk.iloc[0][c] for c in sort_cols)
                if prev_last_sort_key is not None and first_sort < prev_last_sort_key:
                    raise ValueError(f"{path}: rows are not sorted by {sort_cols} across chunk boundary")
                if unique_cols is not None:
                    first_unique = tuple(chunk.iloc[0][c] for c in unique_cols)
                    if prev_last_unique_key is not None and first_unique == prev_last_unique_key:
                        raise ValueError(f"{path}: duplicate key row across chunk boundary on {unique_cols}")
                    prev_last_unique_key = tuple(chunk.iloc[-1][c] for c in unique_cols)
                prev_last_sort_key = tuple(chunk.iloc[-1][c] for c in sort_cols)
            yield chunk
    finally:
        reader.close()


def _coverage_by_group(chunks, group_cols, day_col="day"):
    """Accumulate per-group day coverage: count, min, max, distinct days.

    Valid because inputs are verified sorted and duplicate-free, so
    per-chunk distinct-day counts sum to the global distinct count.
    Returns {group_key: (count, min_day, max_day, distinct_days)}.
    """
    stats: dict = {}
    for chunk in chunks:
        grouped = chunk.groupby(group_cols)["day"].agg(["count", "min", "max", "nunique"])
        for key, row in grouped.iterrows():
            k = key if isinstance(key, tuple) else (key,)
            prev = stats.get(k, (0, None, None, 0))
            stats[k] = (
                prev[0] + int(row["count"]),
                int(row["min"]) if prev[1] is None else min(prev[1], int(row["min"])),
                int(row["max"]) if prev[2] is None else max(prev[2], int(row["max"])),
                prev[3] + int(row["nunique"]),
            )
    return stats


def _check_contiguous(stats: dict, label: str, test_start: int, test_end: int, require_full_from_zero: bool = False) -> tuple[int, int]:
    """Require every group's days to be contiguous, complete, and cover the test window.

    Returns the (global min day, global max day) over all groups.
    """
    if not stats:
        raise ValueError(f"{label}: no data rows")
    gmin, gmax = None, None
    for key, (count, dmin, dmax, distinct) in stats.items():
        expected = dmax - dmin + 1
        if distinct != expected or count != expected:
            raise ValueError(
                f"{label}: group {key} has gaps/duplicates: {count} rows, "
                f"{distinct} distinct days over [{dmin}, {dmax}] (expected {expected})"
            )
        if dmin > test_start or dmax < test_end:
            raise ValueError(
                f"{label}: group {key} range [{dmin}, {dmax}] does not cover "
                f"test window [{test_start}, {test_end}]"
            )
        if require_full_from_zero and dmin != 0:
            raise ValueError(f"{label}: group {key} starts at day {dmin}, expected 0")
        gmin = dmin if gmin is None else min(gmin, dmin)
        gmax = dmax if gmax is None else max(gmax, dmax)
    return gmin, gmax


def _load_frozen_demand(path: Path, test_start: int, test_end: int, chunksize: int):
    """Load frozen demand; validate schema, sortedness, duplicates, coverage."""
    chunks = list(_read_validated_chunks(path, DEMAND_REQUIRED, ["day", "item"], ["day", "item"], chunksize))
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=DEMAND_REQUIRED)
    if df.empty:
        raise ValueError(f"frozen demand is empty: {path}")
    df["day"] = df["day"].astype(int)
    df["demand"] = df["demand"].astype(int)
    stats = _coverage_by_group([df], ["item"])
    _check_contiguous(stats, f"frozen demand {path}", test_start, test_end, require_full_from_zero=True)
    return df


def _compute_model_metrics(
    daily: pd.DataFrame,
    inv_agg: dict,
    backlog_agg: dict,
    ship_units_test: float,
    test_start: int,
    test_end: int,
    destination_node: str,
) -> dict:
    """Compute test-window metrics from validated records.

    inv_agg / backlog_agg: {"daily_sum": {day: sum over all rows that
    day}, "daily_dest_sum": {day: sum over destination rows that day},
    "n_rows": int, "n_dest_rows": int} accumulated over test-window rows.
    Levels are DAILY AGGREGATES: mean/max are taken across test days
    of the per-day sums (aggregation version
    inventory-metrics-v2-daily-aggregate).
    """
    test = daily[(daily["day"] >= test_start) & (daily["day"] <= test_end)]
    if test.empty:
        raise ValueError("no daily records in the test window")
    test_demand = float(test["demand"].sum())
    test_served = float(test["served_from_stock"].sum())
    total_unfilled = float(test["new_backlog_today"].sum())
    if test_demand <= 0:
        raise ValueError("test-window demand is not positive; fill rate undefined")
    fill_rate = test_served / test_demand
    # Identity check: same window, same population (per-row served + unfilled
    # = demand is guaranteed by the simulator; verify it here).
    identity_gap = abs(fill_rate - (1.0 - total_unfilled / test_demand))
    if identity_gap > 1e-9:
        raise ValueError(
            f"fill-rate identity failed: fill_rate={fill_rate}, "
            f"1 - unfilled/demand={1.0 - total_unfilled / test_demand}, gap={identity_gap}"
        )
    expected_days = set(range(test_start, test_end + 1))
    for agg, name in ((inv_agg, "inventory"), (backlog_agg, "backlog")):
        if set(agg["daily_sum"]) != expected_days or set(agg["daily_dest_sum"]) != expected_days:
            raise ValueError(
                f"{name}: daily series does not cover every test day "
                f"[{test_start}, {test_end}]"
            )
    dest_inv_daily = pd.Series(inv_agg["daily_dest_sum"]).sort_index()
    network_daily = pd.Series(inv_agg["daily_sum"]).sort_index()
    dest_backlog_daily = pd.Series(backlog_agg["daily_dest_sum"]).sort_index()
    return {
        "test_start": test_start,
        "test_end": test_end,
        "test_demand": test_demand,
        "test_served": test_served,
        "fill_rate": fill_rate,
        "total_unfilled_demand": total_unfilled,
        "average_destination_inventory": float(dest_inv_daily.mean()),
        "maximum_destination_inventory": float(dest_inv_daily.max()),
        "average_total_network_inventory": float(network_daily.mean()),
        "maximum_total_network_inventory": float(network_daily.max()),
        "average_destination_backlog": float(dest_backlog_daily.mean()),
        "maximum_destination_backlog": float(dest_backlog_daily.max()),
        "final_destination_backlog": float(dest_backlog_daily.loc[test_end]),
        "total_shipment_units_test_window": ship_units_test,
        "fill_rate_identity_gap": identity_gap,
    }


def _accumulate_history(path: Path, required: list[str], key_cols: list[str], unique_cols: list[str], value_col: str,
                        test_start: int, test_end: int, destination_node: str, chunksize: int) -> dict:
    """Accumulate test-window DAILY sums (all nodes + destination) + coverage.

    Also validates coverage per (node, item) over the file's full range.
    Returns (agg, coverage) where agg = {"daily_sum": {day: sum over all
    (node, item) rows that day}, "daily_dest_sum": {day: sum over
    destination-node rows that day}, "n_rows": int, "n_dest_rows": int}.
    Mean/max are taken across test days of these per-day sums (daily
    aggregates), not across individual rows.
    """
    daily_sum: dict[int, float] = {}
    daily_dest_sum: dict[int, float] = {}
    n_rows = 0
    n_dest_rows = 0
    coverage: dict = {}
    for chunk in _read_validated_chunks(path, required, key_cols, unique_cols, chunksize):
        chunk = chunk.copy()
        chunk["day"] = chunk["day"].astype(int)
        chunk[value_col] = chunk[value_col].astype(float)
        grouped = chunk.groupby(["node", "item"])["day"].agg(["count", "min", "max", "nunique"])
        for key, row in grouped.iterrows():
            prev = coverage.get(key, (0, None, None, 0))
            coverage[key] = (
                prev[0] + int(row["count"]),
                int(row["min"]) if prev[1] is None else min(prev[1], int(row["min"])),
                int(row["max"]) if prev[2] is None else max(prev[2], int(row["max"])),
                prev[3] + int(row["nunique"]),
            )
        test_rows = chunk[(chunk["day"] >= test_start) & (chunk["day"] <= test_end)]
        if not test_rows.empty:
            for day, total in test_rows.groupby("day")[value_col].sum().items():
                daily_sum[int(day)] = daily_sum.get(int(day), 0.0) + float(total)
            dest_rows = test_rows[test_rows["node"] == destination_node]
            if not dest_rows.empty:
                for day, total in dest_rows.groupby("day")[value_col].sum().items():
                    daily_dest_sum[int(day)] = daily_dest_sum.get(int(day), 0.0) + float(total)
            n_rows += int(len(test_rows))
            n_dest_rows += int(len(dest_rows))
    if not daily_sum:
        raise ValueError(f"{path}: no rows in the test window")
    if not daily_dest_sum:
        raise ValueError(f"{path}: no destination-node ({destination_node}) rows in the test window")
    return (
        {"daily_sum": daily_sum, "daily_dest_sum": daily_dest_sum,
         "n_rows": n_rows, "n_dest_rows": n_dest_rows},
        coverage,
    )


def _accumulate_shipments(path: Path, test_start: int, test_end: int, chunksize: int) -> float:
    total = 0.0
    for chunk in _read_validated_chunks(path, SHIP_REQUIRED, ["day", "arrival_day", "from", "to", "item"], None, chunksize):
        chunk = chunk.copy()
        chunk["day"] = chunk["day"].astype(int)
        chunk["units"] = chunk["units"].astype(float)
        if (chunk["units"] < 0).any():
            raise ValueError(f"{path}: negative shipment units")
        test_rows = chunk[(chunk["day"] >= test_start) & (chunk["day"] <= test_end)]
        total += float(test_rows["units"].sum())
    return total


def _check_forecast_crosscheck(forecast_path: Path, test_demand: float, test_start: int, test_end: int, chunksize: int) -> dict:
    """Optional cross-check: forecast actuals summed over the test window must equal inventory test demand."""
    if not forecast_path.exists():
        raise FileNotFoundError(f"forecast file not found: {forecast_path}")
    total = 0.0
    n_rows = 0
    for chunk in pd.read_csv(forecast_path, chunksize=chunksize):
        if "day" not in chunk.columns or "actual" not in chunk.columns:
            raise ValueError(f"{forecast_path}: forecast file needs day and actual columns for the cross-check")
        chunk = chunk.copy()
        chunk["day"] = chunk["day"].astype(int)
        chunk["actual"] = chunk["actual"].astype(float)
        test_rows = chunk[(chunk["day"] >= test_start) & (chunk["day"] <= test_end)]
        total += float(test_rows["actual"].sum())
        n_rows += int(len(test_rows))
    gap = abs(total - test_demand)
    if gap > 1e-6:
        raise ValueError(
            f"forecast cross-check failed: forecast actuals sum {total} != "
            f"inventory test demand {test_demand} (gap {gap})"
        )
    return {"forecast_file": str(forecast_path), "forecast_test_actuals": total, "gap": gap, "n_test_rows": n_rows}


def recompute_from_manifest(manifest: dict, test_start: int = TEST_START_DEFAULT,
                            test_end: int = TEST_END_DEFAULT,
                            destination_node: str = DESTINATION_NODE_DEFAULT,
                            chunksize: int = CHUNKSIZE_DEFAULT) -> tuple[pd.DataFrame, dict]:
    """Recompute inventory outcomes for every (scenario, model) in the manifest."""
    if test_start > test_end:
        raise ValueError(f"test_start {test_start} > test_end {test_end}")
    scenarios = manifest.get("scenarios", [])
    if not scenarios:
        raise ValueError("manifest contains no scenarios")
    rows = []
    validation_notes: list[str] = []
    global_item_set: set | None = None
    for scen in scenarios:
        scenario = scen["scenario"]
        demand_df = _load_frozen_demand(Path(scen["demand_file"]), test_start, test_end, chunksize)
        demand_items = set(demand_df["item"].unique().tolist())
        if global_item_set is None:
            global_item_set = demand_items
        elif demand_items != global_item_set:
            raise ValueError(
                f"scenario {scenario}: item set {sorted(demand_items)} != "
                f"item set of earlier scenarios {sorted(global_item_set)}"
            )
        frozen_test_demand = float(
            demand_df[(demand_df["day"] >= test_start) & (demand_df["day"] <= test_end)]["demand"].sum()
        )
        full_horizon_demand = float(demand_df["demand"].sum())
        for model_entry in scen["models"]:
            model = model_entry["model"]
            inv_dir = Path(model_entry["inventory_dir"])
            for fname in INVENTORY_FILES:
                if not (inv_dir / fname).exists():
                    raise FileNotFoundError(f"missing required file: {inv_dir / fname}")
            daily_chunks = list(_read_validated_chunks(inv_dir / "daily_records.csv", DAILY_REQUIRED, ["day", "item"], ["day", "item"], chunksize))
            daily = pd.concat(daily_chunks, ignore_index=True) if daily_chunks else pd.DataFrame(columns=DAILY_REQUIRED)
            daily["day"] = daily["day"].astype(int)
            for col in ("demand", "served_from_stock", "new_backlog_today"):
                daily[col] = daily[col].astype(float)
            # Coverage + item set for daily records.
            daily_stats = _coverage_by_group([daily], ["item"])
            _check_contiguous(daily_stats, f"{scenario}/{model} daily_records", test_start, test_end)
            daily_items = set(daily["item"].unique().tolist())
            if daily_items != demand_items:
                raise ValueError(
                    f"{scenario}/{model}: inventory item set {sorted(daily_items)} != "
                    f"frozen-demand item set {sorted(demand_items)}"
                )
            # Demand-inventory consistency per (day, item).
            merged = daily.merge(
                demand_df, on=["day", "item"], how="outer", suffixes=("_inv", "_frozen"), indicator=True
            )
            if (merged["_merge"] != "both").any():
                raise ValueError(f"{scenario}/{model}: daily records and frozen demand cover different (day, item) keys")
            mismatch = merged[merged["demand_inv"] != merged["demand_frozen"]]
            if not mismatch.empty:
                first = mismatch.iloc[0]
                raise ValueError(
                    f"{scenario}/{model}: inventory demand != frozen demand at "
                    f"day={first['day']}, item={first['item']}: "
                    f"{first['demand_inv']} vs {first['demand_frozen']}"
                )
            inv_agg, inv_cov = _accumulate_history(
                inv_dir / "inventory_history.csv", INV_REQUIRED, ["day", "node", "item"], ["day", "node", "item"],
                "on_hand", test_start, test_end, destination_node, chunksize,
            )
            _check_contiguous(inv_cov, f"{scenario}/{model} inventory_history", test_start, test_end)
            backlog_agg, backlog_cov = _accumulate_history(
                inv_dir / "backlog_history.csv", BACKLOG_REQUIRED, ["day", "node", "item"], ["day", "node", "item"],
                "backlog", test_start, test_end, destination_node, chunksize,
            )
            _check_contiguous(backlog_cov, f"{scenario}/{model} backlog_history", test_start, test_end)
            ship_units = _accumulate_shipments(inv_dir / "shipments.csv", test_start, test_end, chunksize)
            metrics = _compute_model_metrics(
                daily, inv_agg, backlog_agg, ship_units, test_start, test_end, destination_node
            )
            # Test demand from inventory records must equal frozen-demand test sum.
            if abs(metrics["test_demand"] - frozen_test_demand) > 1e-6:
                raise ValueError(
                    f"{scenario}/{model}: inventory test demand {metrics['test_demand']} != "
                    f"frozen-demand test sum {frozen_test_demand}"
                )
            row = {
                "scenario": scenario,
                "model": model,
                "aggregation_version": "inventory-metrics-v2-daily-aggregate",
                "test_demand": metrics["test_demand"],
                "test_served": metrics["test_served"],
                "fill_rate": metrics["fill_rate"],
                "total_unfilled_demand": metrics["total_unfilled_demand"],
                "average_destination_inventory": metrics["average_destination_inventory"],
                "maximum_destination_inventory": metrics["maximum_destination_inventory"],
                "average_total_network_inventory": metrics["average_total_network_inventory"],
                "maximum_total_network_inventory": metrics["maximum_total_network_inventory"],
                "average_destination_backlog": metrics["average_destination_backlog"],
                "maximum_destination_backlog": metrics["maximum_destination_backlog"],
                "final_destination_backlog": metrics["final_destination_backlog"],
                "total_shipment_units_test_window": metrics["total_shipment_units_test_window"],
                "full_horizon_demand": full_horizon_demand,
            }
            rows.append(row)
            validation_notes.append(
                f"{scenario}/{model}: fill-rate identity gap {metrics['fill_rate_identity_gap']:.2e}; "
                f"test demand matches frozen demand; coverage complete."
            )
            if scen.get("forecast_file"):
                check = _check_forecast_crosscheck(
                    Path(scen["forecast_file"]), metrics["test_demand"], test_start, test_end, chunksize
                )
                validation_notes.append(f"{scenario}/{model}: forecast cross-check passed (gap {check['gap']:.2e}).")
    results = pd.DataFrame(rows)
    metadata = {
        "script": "recompute_inventory_windows.py (F01)",
        "aggregation_version": "inventory-metrics-v2-daily-aggregate",
        "test_start": test_start,
        "test_end": test_end,
        "destination_node": destination_node,
        "definitions": {
            "aggregation_version": "inventory-metrics-v2-daily-aggregate: inventory/backlog levels are daily aggregates (sum across items/nodes per day; mean/max across test days), matching the 7300-day notebook and the short-horizon runner",
            "test_demand": "sum(demand) in daily_records over test window; equals frozen-demand test sum",
            "fill_rate": "test_served / test_demand",
            "total_unfilled_demand": "sum(new_backlog_today) over test window",
            "fill_rate_identity": "fill_rate = 1 - total_unfilled_demand / test_demand (same window/population); verified per row-group",
            "average_destination_inventory": "mean over test days of the daily destination total (sum of inventory_history on_hand across items at the destination node; end-of-day snapshots)",
            "maximum_destination_inventory": "max over test days of the same daily destination total",
            "average_total_network_inventory": "mean over test days of the daily network total (sum of inventory_history on_hand across all nodes and items)",
            "maximum_total_network_inventory": "max over test days of the same daily network total",
            "average_destination_backlog": "mean over test days of the daily destination backlog total (sum of backlog_history backlog across items at the destination node)",
            "maximum_destination_backlog": "max over test days of the same daily destination backlog total",
            "final_destination_backlog": "daily destination backlog total on day test_end (sum across items)",
            "total_shipment_units_test_window": "sum of shipments units where dispatch day in test window; a throughput measure, not demand fulfilled",
            "full_horizon_demand": "sum of frozen demand over ALL days; separately labelled descriptive total, never a test-window denominator",
        },
        "inputs": manifest,
        "validation": validation_notes,
        "provenance": "Recomputed from frozen source CSVs listed in inputs. No values are copied from the locked table or slides.",
    }
    out_cols = [
        "scenario", "model", "aggregation_version", "test_demand", "test_served", "fill_rate",
        "total_unfilled_demand", "average_destination_inventory",
        "maximum_destination_inventory", "average_total_network_inventory",
        "maximum_total_network_inventory", "average_destination_backlog",
        "maximum_destination_backlog", "final_destination_backlog",
        "total_shipment_units_test_window", "full_horizon_demand",
    ]
    return results[out_cols], metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="JSON manifest (see module docstring)")
    parser.add_argument("--output-dir", required=True, help="directory for recomputed outputs")
    parser.add_argument("--test-start", type=int, default=TEST_START_DEFAULT)
    parser.add_argument("--test-end", type=int, default=TEST_END_DEFAULT)
    parser.add_argument("--destination-node", default=DESTINATION_NODE_DEFAULT)
    parser.add_argument("--chunksize", type=int, default=CHUNKSIZE_DEFAULT)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    results, metadata = recompute_from_manifest(
        manifest, args.test_start, args.test_end, args.destination_node, args.chunksize
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "recomputed_inventory_outcomes.csv", index=False)
    (out_dir / "recomputed_inventory_metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"wrote {len(results)} rows to {out_dir / 'recomputed_inventory_outcomes.csv'}")


if __name__ == "__main__":
    main()
