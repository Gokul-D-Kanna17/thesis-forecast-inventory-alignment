"""Forecast-accuracy vs inventory-decision ranking alignment.

Reads runner-schema outputs (thesis_short_horizon_experiments.py):
  - forecast item metrics: horizon_days, scenario, model, item, MAE, RMSE, MASE
  - inventory outcomes:   horizon_days, scenario, model, fill_rate,
                          total_unfilled_demand, average_destination_inventory,
                          average_destination_backlog,
                          maximum_destination_backlog,
                          average_total_network_inventory, ...

The script recomputes model ranks FROM VALUES (it does not trust any
precomputed rank column), joins forecast ranks with inventory ranks on
(horizon_days, scenario, model), and reports rank differences and
agreement statistics.

METHOD AND LIMITATIONS (read before using the output)
-----------------------------------------------------
1. Desirability. For fill rate (higher numerical direction) and unfilled
   demand (lower numerical direction), the ranking direction coincides with
   desirability. The remaining inventory measures are OPERATIONAL
   OUTCOMES, not desirability scores: lower inventory is not automatically
   better without an explicit cost or service objective; lower backlog is
   generally desirable but trades against inventory; shipment units are a
   throughput measure, not a quality measure. This script ranks each metric
   separately as a DIRECTION-ORIENTED RANK (best rank under the specified
   numerical direction) and NEVER combines metrics into a composite or
   universal inventory-performance score. A better direction-oriented rank
   on one inventory metric is not "better inventory performance" in general.

2. Repeated comparisons, not independent observations. The 288
   combinations (4 horizons x 4 scenarios x 3 forecast metrics x 6 primary
   inventory metrics) are repeated descriptive comparisons of the same
   models, scenarios, and data. They are NOT 288 independent observations.
   This script reports descriptive summaries only. It computes NO pooled
   inferential statistics, NO confidence intervals, NO standard errors, and
   NO p-values. Do not add any.

3. Small n. Ranks are over models (n = 3 in this study). With n = 3 and no
   ties, Spearman rho can only take values in {-1, -0.5, 0, 0.5, 1}: a
   single rank swap moves rho by 0.5. Kendall tau-b over 3 pairs is equally
   coarse. Both are DESCRIPTIVE ONLY and are reported for completeness, not
   as evidence of association strength.

4. Two distinct agreement estimands (do not conflate them):
   - model-level exact agreement: share of (combination, model) rows with
     rank difference exactly 0.
   - complete-ordering agreement: share of combinations in which the full
     forecast rank vector equals the full inventory rank vector.
   The 288-combination framework counts combinations; the model-level share
   counts rows (3 per combination). Both are reported, labelled.

5. Redundant pair. Within one (horizon, scenario), fill_rate and
   total_unfilled_demand satisfy fill_rate = 1 - unfilled/test_demand
   (per-row served + unfilled = demand in the simulator), so their rank
   orderings are identical by construction. They are NOT independent
   evidence. The script checks this and reports it; the effective number
   of distinct inventory dimensions is 5, not 6. The summary therefore
   includes, alongside the six-metric primary analysis, a SENSITIVITY
   ANALYSIS excluding one of the redundant pair (total_unfilled_demand;
   excluding fill_rate instead would give identical results because the
   rank orderings are identical).

6. Mechanism dependence. Alignment is measured under ONE decision
   mechanism (forecast-driven destination pipeline target; (s,S)
   warehouses fixed). A different mechanism could give different
   alignment. Inventory outcomes also reflect the state inherited at the
   start of the test window (backlog, inventory, in-transit), not
   forecasts alone.

7. Mean-based ranks. Forecast ranks use MEAN-of-item MAE/RMSE/MASE for
   the primary analysis. Median-of-item ranks are computed as a
   SEPARATE SENSITIVITY analysis (forecast errors are right-skewed for
   some models), labelled as such; inventory ranks are unchanged.
   Aggregation used is recorded for every result.

8. Scope. This script works on RUNNER-schema outputs. It does not verify
   thesis results: until it is run on real experiment outputs, its
   correctness rests on the synthetic tests only. The 7300-day notebook
   values need a separate adapter (not included) because they live in
   MASTER CSVs with a different schema.

9. Window validation. Forecast evaluation days (from the day-level
   forecasts file) must cover EXACTLY the inventory test window: for every
   (horizon, scenario, model, item), exactly one forecast row for every day
   from test_start through test_end. Endpoint checks alone are
   insufficient (a file could cover 6200, 6201, 6203, ..., 7299 and pass
   min/max checks despite missing day 6202). Duplicate
   (horizon, scenario, model, item, day) rows are rejected. All models in
   one (horizon, scenario) must share the SAME test window, and the item
   sets in the day-level forecasts must match those in the item metrics.
   Missing day/test_start/test_end metadata fails explicitly;
   comparability is never assumed.

10. Model-set validation. Every (horizon, scenario) group must contain
    exactly the intended models (default: Seasonal Naive, ETS, LightGBM)
    in both inputs. A group missing a model is rejected even if both
    inputs are missing the same model.

11. Grid validation. Both inputs must contain exactly the full intended
    (horizon, scenario) grid (default: the runner's 3 horizons x 4
    scenarios = 12 combinations). An entire combination absent from both
    inputs is rejected. The full 16-combination thesis grid (adding the
    7300-day notebook horizon) is available via --expected-horizons once
    the notebook adapter exists.

12. Finite values. Non-finite metric values (NaN, +inf, -inf) in the
    forecast item metrics, the inventory outcomes, or the day-level
    forecasts are rejected explicitly. A non-finite value must never
    silently produce a rank or an agreement statistic.

13. Appendix-style breakdowns. Horizon-level and scenario-level mean
    absolute rank differences are rebuilt from the SAME underlying
    alignment table, with exact denominators (model-row counts)
    recorded. The breakdowns must reproduce the overall mean absolute
    rank difference as a denominator-weighted mean; a mismatch is an
    error, not a rounding artefact.

No outcome values are hardcoded in this script. No thesis result is
claimed by running it on synthetic data.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

# Primary inventory metrics: runner column name -> specified numerical
# direction for the direction-oriented rank. The direction is a numerical
# convention for ranking, NOT a claim that the value is desirable
# (see module docstring point 1).
PRIMARY_INVENTORY_METRICS = {
    "fill_rate": "higher",
    "total_unfilled_demand": "lower",
    "average_destination_inventory": "lower",
    "average_destination_backlog": "lower",
    "maximum_destination_backlog": "lower",
    "average_total_network_inventory": "lower",
}

# Models the study intends to compare. align() rejects any
# (horizon, scenario) group whose model set differs from this set, even
# if both inputs are missing the same model. Override via --expected-models.
EXPECTED_MODELS = ("Seasonal Naive", "ETS", "LightGBM")

FORECAST_METRICS = ("MAE", "RMSE", "MASE")

FORECAST_ITEM_REQUIRED = [
    "horizon_days",
    "scenario",
    "model",
    "item",
    "MAE",
    "RMSE",
    "MASE",
]

INVENTORY_OUTCOME_REQUIRED = [
    "horizon_days",
    "scenario",
    "model",
    "test_start",
    "test_end",
] + list(PRIMARY_INVENTORY_METRICS)

# Day-level forecasts (runner test_forecasts.csv / all_test_forecasts.csv).
# The window validation needs the evaluation day of every forecast.
FORECASTS_REQUIRED = [
    "horizon_days",
    "scenario",
    "model",
    "item",
    "day",
]


def validate_forecast_window(forecasts: pd.DataFrame, outcomes: pd.DataFrame) -> None:
    """Check forecast evaluation days against the inventory test window.

    For every (horizon_days, scenario, model, item): exactly one forecast
    row for every day from test_start through test_end. Endpoint checks
    alone are insufficient (a file could span [test_start, test_end] while
    missing an interior day). Duplicate rows are rejected. All models in
    one (horizon, scenario) must share the SAME test window. Any mismatch,
    missing test_start/test_end, or missing metadata fails explicitly;
    comparability is never assumed.
    """
    _validate_columns(forecasts, FORECASTS_REQUIRED, "day-level forecasts")
    _validate_columns(outcomes, ["horizon_days", "scenario", "model", "test_start", "test_end"], "inventory outcomes")
    _check_no_missing(
        forecasts, ["horizon_days", "scenario", "model", "day"], "day-level forecasts"
    )
    for col in ("forecast", "actual"):
        if col in forecasts.columns:
            _check_finite(forecasts, [col], "day-level forecasts")
    _check_no_missing(
        outcomes, ["horizon_days", "scenario", "model", "test_start", "test_end"],
        "inventory outcomes",
    )
    if outcomes.duplicated(subset=["horizon_days", "scenario", "model"]).any():
        raise ValueError(
            "inventory outcomes: duplicate (horizon_days, scenario, model) rows"
        )
    # Common test window across models within each (horizon, scenario):
    # matching each model's forecasts to its OWN window does not establish
    # comparability across models.
    for (horizon, scenario), grp in outcomes.groupby(["horizon_days", "scenario"]):
        if grp["test_start"].nunique() != 1 or grp["test_end"].nunique() != 1:
            raise ValueError(
                "inventory outcomes: models in "
                f"(horizon_days={horizon}, scenario={scenario}) have different "
                "test windows: "
                f"{grp[['model', 'test_start', 'test_end']].to_dict('records')}; "
                "inventory outcomes are not directly comparable across models"
            )
    for _, row in outcomes.iterrows():
        if not (row["test_start"] <= row["test_end"]):
            raise ValueError(
                "inventory outcomes: invalid test window for "
                f"({row['horizon_days']}, {row['scenario']}, {row['model']}): "
                f"test_start={row['test_start']} > test_end={row['test_end']}"
            )
    window = outcomes.set_index(["horizon_days", "scenario", "model"])[["test_start", "test_end"]]
    forecast_keys = set(
        map(tuple, forecasts[["horizon_days", "scenario", "model"]].drop_duplicates().values)
    )
    outcome_keys = set(map(tuple, window.index.tolist()))
    if forecast_keys != outcome_keys:
        raise ValueError(
            "day-level forecasts and inventory outcomes cover different "
            f"(horizon_days, scenario, model) sets: "
            f"only-in-forecasts={sorted(forecast_keys - outcome_keys)[:5]}, "
            f"only-in-outcomes={sorted(outcome_keys - forecast_keys)[:5]}"
        )
    # Complete daily coverage: for every (horizon, scenario, model, item),
    # exactly one forecast row for every day from test_start through
    # test_end. Checking min/max alone is insufficient: a file covering
    # 6200, 6201, 6203, ..., 7299 would pass endpoint checks despite
    # missing day 6202. Duplicate (horizon, scenario, model, item, day)
    # rows are rejected as well.
    dup_mask = forecasts.duplicated(
        subset=["horizon_days", "scenario", "model", "item", "day"], keep=False
    )
    if bool(dup_mask.any()):
        dup_rows = forecasts.loc[
            dup_mask, ["horizon_days", "scenario", "model", "item", "day"]
        ]
        raise ValueError(
            "day-level forecasts: duplicate (horizon, scenario, model, item, day) "
            f"rows: {dup_rows.head(10).to_dict('records')}"
        )
    for (horizon, scenario, model, item), grp in forecasts.groupby(
        ["horizon_days", "scenario", "model", "item"]
    ):
        test_start, test_end = window.loc[(horizon, scenario, model)]
        test_start, test_end = int(test_start), int(test_end)
        window_len = test_end - test_start + 1
        n_rows = len(grp)
        n_days = int(grp["day"].nunique())
        day_min, day_max = int(grp["day"].min()), int(grp["day"].max())
        if (
            n_rows == window_len
            and n_days == n_rows
            and day_min == test_start
            and day_max == test_end
        ):
            continue  # fast path: counts + endpoints prove complete coverage
        days = set(grp["day"].tolist())
        expected_days = set(range(test_start, test_end + 1))
        missing = sorted(expected_days - days)[:10]
        extra = sorted(days - expected_days)[:10]
        raise ValueError(
            "day-level forecasts: incomplete daily coverage for "
            f"(horizon_days={horizon}, scenario={scenario}, model={model}, item={item}): "
            f"{n_rows} rows, {n_days} distinct days, span [{day_min}, {day_max}], "
            f"window [{test_start}, {test_end}]; missing days (first 10)={missing}; "
            f"extra days (first 10)={extra}"
        )


def _validate_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing required columns: {missing}")
    if df.empty:
        raise ValueError(f"{name}: input is empty")


def _check_no_missing(df: pd.DataFrame, columns: list[str], name: str) -> None:
    bad = df[columns].isna().any()
    if bool(bad.any()):
        raise ValueError(
            f"{name}: missing values in columns: "
            f"{[c for c in columns if bad[c]]}"
        )


def _check_finite(df: pd.DataFrame, columns: list[str], name: str) -> None:
    """Reject non-finite (NaN, +inf, -inf) or non-numeric values."""
    for col in columns:
        vals = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(vals).all():
            raise ValueError(
                f"{name}: non-finite or non-numeric values in column {col}; "
                "non-finite values must never silently produce a rank"
            )


def compute_forecast_ranks(item_metrics: pd.DataFrame, aggregation: str = "mean") -> pd.DataFrame:
    """Forecast metrics per (horizon, scenario, model), ranked.

    ``aggregation`` selects how item-level MAE/RMSE/MASE are combined
    across items before ranking: "mean" (primary analysis) or "median"
    (sensitivity analysis). The aggregation used is recorded in the
    returned frame's ``aggregation`` column.

    Returns columns: horizon_days, scenario, model, metric, value, rank,
    aggregation. Rank 1 = smallest forecast error (ascending), average
    tie method.

    Validation: within each (horizon, scenario), every model must be
    evaluated on the IDENTICAL SET of item IDs (equal counts are not
    enough), and no (horizon, scenario, model, item) record may appear
    more than once. Non-finite metric values are rejected. Both
    conditions are rejected with an explicit error.
    """
    if aggregation not in ("mean", "median"):
        raise ValueError(f"aggregation must be 'mean' or 'median', got {aggregation!r}")
    _validate_columns(item_metrics, FORECAST_ITEM_REQUIRED, "forecast item metrics")
    _check_no_missing(
        item_metrics, ["horizon_days", "scenario", "model", "item"] + list(FORECAST_METRICS),
        "forecast item metrics",
    )
    _check_finite(item_metrics, list(FORECAST_METRICS), "forecast item metrics")
    # Reject duplicate item-level records: one row per
    # (horizon, scenario, model, item).
    dup_mask = item_metrics.duplicated(
        subset=["horizon_days", "scenario", "model", "item"], keep=False
    )
    if bool(dup_mask.any()):
        dup_rows = item_metrics.loc[dup_mask, ["horizon_days", "scenario", "model", "item"]]
        raise ValueError(
            "forecast item metrics: duplicate item-level records for "
            f"(horizon, scenario, model, item): {dup_rows.head(10).to_dict('records')}"
        )
    # Every model must be evaluated on the identical SET of item IDs within
    # a (horizon, scenario) group; equal counts are insufficient.
    for (horizon, scenario), grp in item_metrics.groupby(["horizon_days", "scenario"]):
        sets = {
            model: set(sub["item"].tolist())
            for model, sub in grp.groupby("model")
        }
        reference = next(iter(sets.values()))
        for model, item_set in sets.items():
            if item_set != reference:
                raise ValueError(
                    "forecast item metrics: item-ID sets differ across models "
                    f"within (horizon_days={horizon}, scenario={scenario}): "
                    f"model {model} has {sorted(item_set - reference)} extra and "
                    f"{sorted(reference - item_set)} missing relative to the "
                    "first model's set"
                )
    agg_fn = "mean" if aggregation == "mean" else "median"
    combined = (
        item_metrics.groupby(["horizon_days", "scenario", "model"])[list(FORECAST_METRICS)]
        .agg(agg_fn)
        .reset_index()
    )
    rows = []
    for metric in FORECAST_METRICS:
        for (horizon, scenario), grp in combined.groupby(["horizon_days", "scenario"]):
            ranks = grp[metric].rank(method="average", ascending=True)
            for (_, row), rank in zip(grp.iterrows(), ranks):
                rows.append(
                    {
                        "horizon_days": horizon,
                        "scenario": scenario,
                        "model": row["model"],
                        "metric": metric,
                        "value": float(row[metric]),
                        "rank": float(rank),
                        "aggregation": aggregation,
                    }
                )
    return pd.DataFrame(rows)


def compute_inventory_ranks(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Inventory-metric ranks per (horizon, scenario, model).

    Returns columns: horizon_days, scenario, model, metric, value, rank.
    Rank 1 = best rank under the specified numerical direction
    (direction-oriented rank; fill_rate: higher direction; all others:
    lower direction), average tie method. Each metric is ranked
    separately; no composite. The direction is a numerical convention for
    ranking, not a claim that the value is desirable (see module
    docstring point 1).
    """
    _validate_columns(outcomes, INVENTORY_OUTCOME_REQUIRED, "inventory outcomes")
    _check_no_missing(
        outcomes,
        ["horizon_days", "scenario", "model"] + list(PRIMARY_INVENTORY_METRICS),
        "inventory outcomes",
    )
    _check_finite(outcomes, list(PRIMARY_INVENTORY_METRICS), "inventory outcomes")
    if outcomes.duplicated(subset=["horizon_days", "scenario", "model"]).any():
        raise ValueError(
            "inventory outcomes: duplicate (horizon_days, scenario, model) rows"
        )
    rows = []
    for metric, direction in PRIMARY_INVENTORY_METRICS.items():
        ascending = direction == "lower"
        for (horizon, scenario), grp in outcomes.groupby(["horizon_days", "scenario"]):
            ranks = grp[metric].rank(method="average", ascending=ascending)
            for (_, row), rank in zip(grp.iterrows(), ranks):
                rows.append(
                    {
                        "horizon_days": horizon,
                        "scenario": scenario,
                        "model": row["model"],
                        "metric": metric,
                        "value": float(row[metric]),
                        "rank": float(rank),
                    }
                )
    return pd.DataFrame(rows)


def spearman_rho(x_ranks, y_ranks) -> float:
    """Spearman rho as Pearson correlation of rank vectors. Descriptive only."""
    x = np.asarray(x_ranks, dtype=float)
    y = np.asarray(y_ranks, dtype=float)
    if len(x) < 2 or len(y) < 2 or len(x) != len(y):
        return float("nan")
    if float(np.std(x)) == 0.0 or float(np.std(y)) == 0.0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def kendall_tau_b(x_ranks, y_ranks) -> float:
    """Kendall tau-b on rank vectors (ties handled). Descriptive only."""
    x = np.asarray(x_ranks, dtype=float)
    y = np.asarray(y_ranks, dtype=float)
    n = len(x)
    if n < 2 or len(y) != n:
        return float("nan")
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            prod = (x[i] - x[j]) * (y[i] - y[j])
            if prod > 0:
                concordant += 1
            elif prod < 0:
                discordant += 1

    def _tie_term(values) -> int:
        _, counts = np.unique(values, return_counts=True)
        return int(sum(int(c) * (int(c) - 1) // 2 for c in counts))

    n0 = n * (n - 1) // 2
    denom = math.sqrt((n0 - _tie_term(x)) * (n0 - _tie_term(y)))
    if denom == 0:
        return float("nan")
    return float((concordant - discordant) / denom)


def validate_forecast_item_sets(forecasts: pd.DataFrame, item_metrics: pd.DataFrame) -> None:
    """Require identical item sets in day-level forecasts and item metrics.

    A missing item in either file would silently compare forecast metrics
    computed over one item set with window validation over another.
    """
    _validate_columns(forecasts, ["horizon_days", "scenario", "model", "item"], "day-level forecasts")
    _validate_columns(item_metrics, ["horizon_days", "scenario", "model", "item"], "forecast item metrics")
    f_keys = set(
        map(tuple, forecasts[["horizon_days", "scenario", "model"]].drop_duplicates().values)
    )
    m_keys = set(
        map(tuple, item_metrics[["horizon_days", "scenario", "model"]].drop_duplicates().values)
    )
    for key in sorted(f_keys | m_keys):
        f_items = set(forecasts[
            (forecasts["horizon_days"] == key[0])
            & (forecasts["scenario"] == key[1])
            & (forecasts["model"] == key[2])
        ]["item"].tolist())
        m_items = set(item_metrics[
            (item_metrics["horizon_days"] == key[0])
            & (item_metrics["scenario"] == key[1])
            & (item_metrics["model"] == key[2])
        ]["item"].tolist())
        if f_items != m_items:
            raise ValueError(
                f"item sets differ between day-level forecasts and forecast item "
                f"metrics for {key}: only-in-forecasts={sorted(f_items - m_items)[:10]}, "
                f"only-in-item-metrics={sorted(m_items - f_items)[:10]}"
            )


# The runner (thesis_short_horizon_experiments.py) produces horizons
# 2000/3000/5000 x scenarios normal/demand_disruption/supply_disruption/
# combined_disruption = 12 combinations (HORIZONS L49-52, SCENARIOS L55+,
# CLI defaults L288-289). The full 16-combination thesis grid adds the
# 7300-day notebook horizon, which needs the notebook adapter (not yet
# built); pass it via --expected-horizons when adapted inputs exist.
EXPECTED_HORIZONS = (2000, 3000, 5000)
EXPECTED_SCENARIOS = (
    "normal",
    "demand_disruption",
    "supply_disruption",
    "combined_disruption",
)


def validate_experiment_grid(
    forecast_ranks: pd.DataFrame,
    inventory_ranks: pd.DataFrame,
    expected_horizons: tuple[int, ...] = EXPECTED_HORIZONS,
    expected_scenarios: tuple[str, ...] = EXPECTED_SCENARIOS,
) -> None:
    """Require the complete intended (horizon, scenario) grid in both inputs.

    Checking only groups that appear would allow an entire combination to
    be absent from both inputs without failing. Both inputs must contain
    exactly the Cartesian product of the expected horizons and scenarios.
    """
    expected = {(h, s) for h in expected_horizons for s in expected_scenarios}
    for label, df in (("forecast", forecast_ranks), ("inventory", inventory_ranks)):
        present = set(
            map(tuple, df[["horizon_days", "scenario"]].drop_duplicates().values)
        )
        if present != expected:
            raise ValueError(
                f"{label} ranks: (horizon_days, scenario) combinations "
                f"{sorted(present)} != expected {sorted(expected)}; "
                f"missing={sorted(expected - present)}, extra={sorted(present - expected)}"
            )


def _validate_complete_model_groups(
    forecast_ranks: pd.DataFrame,
    inventory_ranks: pd.DataFrame,
    expected_models: tuple[str, ...],
) -> None:
    """Require exactly the intended models in every (horizon, scenario).

    A group with a missing model is rejected even if BOTH inputs are
    missing the same model (comparing fewer models would silently change
    what the ranks mean). Extra or renamed models are rejected as well.
    """
    expected = set(expected_models)
    for label, df in (("forecast", forecast_ranks), ("inventory", inventory_ranks)):
        for (horizon, scenario), grp in df.groupby(["horizon_days", "scenario"]):
            models = set(grp["model"].unique().tolist())
            if models != expected:
                raise ValueError(
                    f"{label} ranks: (horizon_days={horizon}, scenario={scenario}) "
                    f"contains models {sorted(models)}, expected exactly "
                    f"{sorted(expected)}; missing={sorted(expected - models)}, "
                    f"extra={sorted(models - expected)}"
                )


def align(
    forecast_ranks: pd.DataFrame,
    inventory_ranks: pd.DataFrame,
    expected_models: tuple[str, ...] = EXPECTED_MODELS,
) -> pd.DataFrame:
    """Join forecast and inventory ranks; compute per-model differences.

    Returns one row per (horizon_days, scenario, forecast_metric,
    inventory_metric, model) with forecast_rank, inventory_rank,
    rank_difference (inventory - forecast), abs_rank_difference, and
    exact_agreement (rank_difference == 0). Per-combination Spearman rho
    and Kendall tau-b are attached (same value for every model row of a
    combination); they are descriptive only (see module docstring).

    Every (horizon, scenario) group must contain exactly the intended
    models in BOTH inputs; incomplete groups are rejected even when both
    inputs are missing the same model.
    """
    _validate_complete_model_groups(forecast_ranks, inventory_ranks, expected_models)
    f = forecast_ranks.rename(
        columns={"metric": "forecast_metric", "value": "forecast_value", "rank": "forecast_rank"}
    )
    inv = inventory_ranks.rename(
        columns={"metric": "inventory_metric", "value": "inventory_value", "rank": "inventory_rank"}
    )
    merged = f.merge(
        inv, on=["horizon_days", "scenario", "model"], how="inner", suffixes=("", "")
    )
    # Every forecast group must have a matching inventory group.
    f_keys = set(
        map(tuple, f[["horizon_days", "scenario", "model"]].drop_duplicates().values)
    )
    inv_keys = set(
        map(tuple, inv[["horizon_days", "scenario", "model"]].drop_duplicates().values)
    )
    if f_keys != inv_keys:
        raise ValueError(
            "forecast and inventory inputs cover different "
            f"(horizon_days, scenario, model) sets: "
            f"only-in-forecast={sorted(f_keys - inv_keys)[:5]}, "
            f"only-in-inventory={sorted(inv_keys - f_keys)[:5]}"
        )
    merged["rank_difference"] = merged["inventory_rank"] - merged["forecast_rank"]
    merged["abs_rank_difference"] = merged["rank_difference"].abs()
    merged["exact_agreement"] = merged["rank_difference"] == 0

    # Per-combination descriptive correlations, attached to every model row
    # of the combination. groupby(sort=True) order matches the sorted frame.
    merged = merged.sort_values(
        ["horizon_days", "scenario", "forecast_metric", "inventory_metric", "model"]
    ).reset_index(drop=True)
    rho_values, tau_values = [], []
    for _, grp in merged.groupby(
        ["horizon_days", "scenario", "forecast_metric", "inventory_metric"]
    ):
        rho = spearman_rho(grp["forecast_rank"], grp["inventory_rank"])
        tau = kendall_tau_b(grp["forecast_rank"], grp["inventory_rank"])
        rho_values.extend([rho] * len(grp))
        tau_values.extend([tau] * len(grp))
    merged["spearman_rho_descriptive"] = rho_values
    merged["kendall_tau_b_descriptive"] = tau_values
    return merged[
        [
            "horizon_days",
            "scenario",
            "forecast_metric",
            "inventory_metric",
            "model",
            "forecast_value",
            "forecast_rank",
            "inventory_value",
            "inventory_rank",
            "rank_difference",
            "abs_rank_difference",
            "exact_agreement",
            "spearman_rho_descriptive",
            "kendall_tau_b_descriptive",
        ]
    ]


def check_fill_unfilled_redundancy(inventory_ranks: pd.DataFrame) -> dict:
    """Check that fill_rate and total_unfilled_demand give identical ranks.

    Within one (horizon, scenario) the simulator satisfies
    fill_rate = 1 - unfilled/test_demand with a common test demand, so the
    two rank orderings must be identical. Returns the share of
    (horizon, scenario) groups where they agree, and the list of groups
    where they do not (a data inconsistency if non-empty).
    """
    pivot = inventory_ranks.pivot_table(
        index=["horizon_days", "scenario", "model"],
        columns="metric",
        values="rank",
    )
    groups, disagree = [], []
    for (horizon, scenario), grp in pivot.groupby(level=[0, 1]):
        groups.append((horizon, scenario))
        fill = grp["fill_rate"].sort_index()
        unfilled = grp["total_unfilled_demand"].sort_index()
        if not fill.index.equals(unfilled.index) or not np.allclose(
            fill.values, unfilled.values
        ):
            disagree.append((horizon, scenario))
    return {
        "n_groups": len(groups),
        "n_groups_agreeing": len(groups) - len(disagree),
        "share_agreeing": (len(groups) - len(disagree)) / len(groups) if groups else float("nan"),
        "disagreeing_groups": [list(g) for g in disagree],
    }


def _summarize_subset(aligned_subset: pd.DataFrame) -> dict:
    """Descriptive summaries for one subset of aligned rows (no inference).

    Horizon-level and scenario-level breakdowns are rebuilt from the
    SAME underlying alignment table (model rows), with exact
    denominators (n_model_rows) recorded. Each breakdown's
    denominator-weighted mean absolute rank difference must reproduce
    the subset's overall mean; a mismatch raises an error.
    """
    combo_rows = []
    for keys, grp in aligned_subset.groupby(
        ["horizon_days", "scenario", "forecast_metric", "inventory_metric"]
    ):
        f_vec = grp.sort_values("model")["forecast_rank"].to_numpy()
        i_vec = grp.sort_values("model")["inventory_rank"].to_numpy()
        combo_rows.append(
            {
                "horizon_days": keys[0],
                "scenario": keys[1],
                "forecast_metric": keys[2],
                "inventory_metric": keys[3],
                "n_models": len(grp),
                "complete_ordering_agreement": bool(np.allclose(f_vec, i_vec)),
                "model_level_exact_share": float(grp["exact_agreement"].mean()),
                "mean_abs_rank_difference": float(grp["abs_rank_difference"].mean()),
                "spearman_rho_descriptive": float(grp["spearman_rho_descriptive"].iloc[0]),
                "kendall_tau_b_descriptive": float(grp["kendall_tau_b_descriptive"].iloc[0]),
            }
        )
    combo_df = pd.DataFrame(combo_rows)
    delta_counts = (
        aligned_subset["rank_difference"].value_counts().sort_index().astype(int).to_dict()
    )
    overall_mean_abs = float(aligned_subset["abs_rank_difference"].mean())
    by_horizon = {}
    for h, g in aligned_subset.groupby("horizon_days"):
        combos_h = combo_df[combo_df["horizon_days"] == h]
        by_horizon[str(h)] = {
            "n_model_rows": int(len(g)),
            "n_combinations": int(len(combos_h)),
            "mean_abs_rank_difference": float(g["abs_rank_difference"].mean()),
            "model_level_exact_agreement_share": float(g["exact_agreement"].mean()),
            "complete_ordering_agreement_share": float(combos_h["complete_ordering_agreement"].mean()),
        }
    by_scenario = {}
    for s, g in aligned_subset.groupby("scenario"):
        combos_s = combo_df[combo_df["scenario"] == s]
        by_scenario[str(s)] = {
            "n_model_rows": int(len(g)),
            "n_combinations": int(len(combos_s)),
            "mean_abs_rank_difference": float(g["abs_rank_difference"].mean()),
            "model_level_exact_agreement_share": float(g["exact_agreement"].mean()),
            "complete_ordering_agreement_share": float(combos_s["complete_ordering_agreement"].mean()),
        }
    # Consistency: the horizon and scenario breakdowns must each
    # reproduce the overall mean as a denominator-weighted mean.
    for label, breakdown in (("by_horizon", by_horizon), ("by_scenario", by_scenario)):
        total_rows = sum(v["n_model_rows"] for v in breakdown.values())
        weighted = sum(v["mean_abs_rank_difference"] * v["n_model_rows"] for v in breakdown.values()) / total_rows
        if not math.isclose(weighted, overall_mean_abs, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"{label}: denominator-weighted mean |rank difference| {weighted} "
                f"!= overall mean {overall_mean_abs}; breakdowns are inconsistent"
            )
    return {
        "n_combinations": int(len(combo_df)),
        "n_model_rows": int(len(aligned_subset)),
        "complete_ordering_agreement_share": float(combo_df["complete_ordering_agreement"].mean()),
        "model_level_exact_agreement_share": float(aligned_subset["exact_agreement"].mean()),
        "mean_abs_rank_difference": overall_mean_abs,
        "rank_difference_distribution": {str(k): int(v) for k, v in delta_counts.items()},
        "by_horizon": by_horizon,
        "by_scenario": by_scenario,
        "by_forecast_metric": {
            str(k): {
                "complete_ordering_agreement_share": float(g["complete_ordering_agreement"].mean()),
                "mean_abs_rank_difference": float(g["mean_abs_rank_difference"].mean()),
            }
            for k, g in combo_df.groupby("forecast_metric")
        },
        "by_inventory_metric": {
            str(k): {
                "complete_ordering_agreement_share": float(g["complete_ordering_agreement"].mean()),
                "mean_abs_rank_difference": float(g["mean_abs_rank_difference"].mean()),
            }
            for k, g in combo_df.groupby("inventory_metric")
        },
    }


def summarize(aligned: pd.DataFrame, inventory_ranks: pd.DataFrame, median_aligned: pd.DataFrame | None = None) -> dict:
    """Descriptive summaries only. No inferential statistics are computed.

    Top-level fields are the six-metric PRIMARY analysis (mean-of-item
    forecast ranks). The nested ``sensitivity_excluding_total_unfilled_demand``
    field repeats the same summaries after dropping one of the redundant
    fill_rate / total_unfilled_demand pair; it is labelled as sensitivity
    analysis. If ``median_aligned`` is given (alignment computed from
    median-of-item forecast ranks), the nested
    ``sensitivity_median_forecast_ranks`` field reports the same
    summaries for that sensitivity; inventory ranks are unchanged.
    """
    primary = _summarize_subset(aligned)
    sensitivity = _summarize_subset(
        aligned[aligned["inventory_metric"] != "total_unfilled_demand"]
    )
    out = {
        **primary,
        "sensitivity_excluding_total_unfilled_demand": {
            **sensitivity,
            "label": (
                "sensitivity analysis: excludes total_unfilled_demand, "
                "redundant with fill_rate (identical rank orderings by "
                "construction). Excluding fill_rate instead would give "
                "identical results."
            ),
        },
        "fill_unfilled_redundancy_check": check_fill_unfilled_redundancy(inventory_ranks),
        "caveats": [
            "Descriptive only: combinations are repeated comparisons, not independent observations.",
            "No confidence intervals, standard errors, or p-values are computed or implied.",
            "Spearman/Kendall values are descriptive; with n=3 models they are coarse and unstable.",
            "Inventory metrics are operational outcomes, not desirability scores; no composite score is constructed.",
            "fill_rate and total_unfilled_demand give identical rankings by construction and are not independent evidence.",
            "Sensitivity analysis excluding total_unfilled_demand is reported alongside the six-metric primary analysis.",
            "Median-of-item forecast ranks are a separate sensitivity analysis (sensitivity_median_forecast_ranks); the primary analysis uses mean-of-item ranks.",
            "Horizon-level and scenario-level breakdowns are rebuilt from the same alignment table; their denominator-weighted means reproduce the overall mean absolute rank difference.",
        ],
    }
    if median_aligned is not None:
        out["sensitivity_median_forecast_ranks"] = {
            **_summarize_subset(median_aligned),
            "label": (
                "sensitivity analysis: forecast ranks from MEDIAN-of-item "
                "MAE/RMSE/MASE (primary uses mean-of-item). Inventory ranks "
                "are unchanged. Mean-vs-median orderings can differ when "
                "item-level errors are right-skewed."
            ),
        }
    return out


def _verify_against_summary(
    forecast_ranks: pd.DataFrame, summary_path: Path | None
) -> list[str]:
    """Optional cross-check: recomputed mean forecast values vs summary file."""
    notes: list[str] = []
    if summary_path is None:
        return notes
    summary = pd.read_csv(summary_path)
    mean_map = {"MAE": "mean_MAE", "RMSE": "mean_RMSE", "MASE": "mean_MASE"}
    for metric, col in mean_map.items():
        if col not in summary.columns:
            notes.append(f"summary file lacks column {col}; skipped check for {metric}")
            continue
        ref = summary.set_index(["horizon_days", "scenario", "model"])[col]
        for _, row in forecast_ranks[forecast_ranks["metric"] == metric].iterrows():
            key = (row["horizon_days"], row["scenario"], row["model"])
            if key in ref.index and not math.isclose(
                float(row["value"]), float(ref.loc[key]), rel_tol=1e-6, abs_tol=1e-9
            ):
                notes.append(
                    f"summary mismatch for {metric} at {key}: "
                    f"recomputed={row['value']}, summary={ref.loc[key]}"
                )
    if not notes:
        notes.append("summary cross-check passed")
    return notes


def _verify_against_rankings(
    inventory_ranks: pd.DataFrame, rankings_path: Path | None
) -> list[str]:
    """Optional cross-check: recomputed inventory ranks vs rankings file."""
    notes: list[str] = []
    if rankings_path is None:
        return notes
    ref = pd.read_csv(rankings_path)
    merged = inventory_ranks.merge(
        ref,
        left_on=["horizon_days", "scenario", "model", "metric"],
        right_on=["horizon_days", "scenario", "model", "metric"],
        suffixes=("_recomputed", "_file"),
        how="outer",
        indicator=True,
    )
    mismatched = merged[(merged["_merge"] == "both") & (~np.isclose(merged["rank_recomputed"], merged["rank_file"]))]
    only_one = merged[merged["_merge"] != "both"]
    if not mismatched.empty:
        notes.append(f"rankings file: {len(mismatched)} rank mismatches vs recomputed")
    if not only_one.empty:
        notes.append(f"rankings file: {len(only_one)} rows present in only one source")
    if not notes:
        notes.append("rankings cross-check passed")
    return notes


def _verify_item_metrics_against_forecasts(
    forecasts: pd.DataFrame, item_metrics: pd.DataFrame
) -> list[str]:
    """Cross-check: recompute item-level MAE/RMSE from day-level forecasts.

    The item metrics file is the runner's output; this check recomputes
    MAE and RMSE independently from the day-level (model, item, day,
    forecast, actual) records and reports mismatches as notes (it does
    not fail the run, because the item metrics are the primary record
    and rounding may differ). MASE CANNOT be recomputed here: it needs
    the training series, which day-level forecasts do not carry; MASE
    recomputation is the F05 script's job (training denominator from
    the frozen demand file).
    """
    notes: list[str] = []
    if "forecast" not in forecasts.columns or "actual" not in forecasts.columns:
        return ["day-level forecasts lack forecast/actual columns; item-metric cross-check skipped"]
    key_cols = ["horizon_days", "scenario", "model", "item"]
    ref = item_metrics.set_index(key_cols)
    for key, grp in forecasts.groupby(key_cols):
        if key not in ref.index:
            notes.append(f"item metrics lack entry for {key}; cross-check skipped for it")
            continue
        err = grp["actual"].to_numpy(dtype=float) - grp["forecast"].to_numpy(dtype=float)
        recomputed = {
            "MAE": float(np.mean(np.abs(err))),
            "RMSE": float(np.sqrt(np.mean(err ** 2))),
        }
        for metric, value in recomputed.items():
            stored = float(ref.loc[key, metric])
            if not math.isclose(value, stored, rel_tol=1e-6, abs_tol=1e-9):
                notes.append(
                    f"item-metric mismatch for {metric} at {key}: "
                    f"recomputed={value}, file={stored}"
                )
    if not notes:
        notes.append(
            "item-metric cross-check passed (MAE/RMSE recomputed from day-level "
            "forecasts; MASE needs training data, see F05)"
        )
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-item-metrics", required=True, help="forecast_item_metrics.csv (runner schema)")
    parser.add_argument("--forecasts", required=True, help="all_test_forecasts.csv (runner schema, day-level); required so forecast evaluation days can be validated against the inventory test window")
    parser.add_argument("--inventory-outcomes", required=True, help="all_inventory_outcomes.csv (runner schema, must include test_start/test_end)")
    parser.add_argument("--expected-models", default=",".join(EXPECTED_MODELS), help="comma-separated intended models; every (horizon, scenario) group must contain exactly this set in both inputs")
    parser.add_argument("--expected-horizons", default=",".join(str(h) for h in EXPECTED_HORIZONS), help="comma-separated intended horizons; both inputs must contain exactly the full horizon x scenario grid")
    parser.add_argument("--expected-scenarios", default=",".join(EXPECTED_SCENARIOS), help="comma-separated intended scenarios; both inputs must contain exactly the full horizon x scenario grid")
    parser.add_argument("--forecast-summary", default=None, help="optional forecast_summary_metrics.csv for cross-check")
    parser.add_argument("--inventory-rankings", default=None, help="optional inventory_metric_rankings.csv for cross-check")
    parser.add_argument("--output-dir", required=True, help="directory for alignment_results.csv and alignment_summary.json")
    args = parser.parse_args()

    expected_models = tuple(m.strip() for m in args.expected_models.split(",") if m.strip())
    if not expected_models:
        raise ValueError("--expected-models must name at least one model")
    try:
        expected_horizons = tuple(int(h) for h in args.expected_horizons.split(",") if h.strip())
    except ValueError as exc:
        raise ValueError(f"--expected-horizons must be comma-separated integers: {args.expected_horizons}") from exc
    expected_scenarios = tuple(s.strip() for s in args.expected_scenarios.split(",") if s.strip())
    if not expected_horizons or not expected_scenarios:
        raise ValueError("--expected-horizons and --expected-scenarios must each name at least one value")
    outcomes = pd.read_csv(args.inventory_outcomes)
    forecasts = pd.read_csv(args.forecasts)
    item_metrics = pd.read_csv(args.forecast_item_metrics)
    validate_forecast_window(forecasts, outcomes)
    validate_forecast_item_sets(forecasts, item_metrics)
    forecast_ranks = compute_forecast_ranks(item_metrics, aggregation="mean")
    inventory_ranks = compute_inventory_ranks(outcomes)
    validate_experiment_grid(
        forecast_ranks, inventory_ranks, expected_horizons, expected_scenarios
    )
    aligned = align(forecast_ranks, inventory_ranks, expected_models=expected_models)
    # Median-of-item forecast ranks: separate sensitivity analysis.
    median_forecast_ranks = compute_forecast_ranks(item_metrics, aggregation="median")
    median_aligned = align(median_forecast_ranks, inventory_ranks, expected_models=expected_models)
    summary = summarize(aligned, inventory_ranks, median_aligned=median_aligned)
    summary["verification_notes"] = _verify_against_summary(
        forecast_ranks, Path(args.forecast_summary) if args.forecast_summary else None
    ) + _verify_against_rankings(
        inventory_ranks, Path(args.inventory_rankings) if args.inventory_rankings else None
    ) + _verify_item_metrics_against_forecasts(forecasts, item_metrics)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    aligned.to_csv(out_dir / "alignment_results.csv", index=False)
    median_aligned.to_csv(out_dir / "alignment_results_median_forecast_ranks.csv", index=False)
    (out_dir / "alignment_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
