"""Tests for the runner's inventory-metric computation and run protection.

The runner itself is never executed here (no simulation run). These tests
call the pure functions in thesis_short_horizon_experiments.py on
hand-computed small fixtures, so they verify the aggregation,
validation, manifest, and overwrite logic without a simulation.

Fixtures mirror the F01 test fixture (2 items, 2 nodes, test days 2..4)
so the runner and the F01 recomputation must agree on the same inputs.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import thesis_short_horizon_experiments as runner

ITEMS = ["I01", "I02"]
NODES = ["NewYork", "WarehouseA"]
TEST_START, TEST_END = 2, 4

DEMAND = {
    0: {"I01": 10, "I02": 20},
    1: {"I01": 12, "I02": 22},
    2: {"I01": 14, "I02": 24},
    3: {"I01": 16, "I02": 26},
    4: {"I01": 18, "I02": 28},
    5: {"I01": 20, "I02": 30},
}
# NewYork inventory: I01 120/130/140, I02 125/135/145 (days 2/3/4).
# WarehouseA inventory: I01 210/215/220, I02 220/225/230.
# NewYork backlog: I01 4/6/8, I02 5/7/9. WarehouseA backlog: 0.


def _frames(ship_extra_out_of_window=True):
    daily, inv, backlog, ship = [], [], [], []
    for day in range(2, 5):
        for item in ITEMS:
            off = 0 if item == "I01" else 5
            demand = DEMAND[day][item]
            daily.append({
                "day": day, "item": item, "demand": demand,
                "served_from_stock": demand - 1, "new_backlog_today": 1,
            })
            ny_inv = 100 + day * 10 + off
            inv.append({"day": day, "node": "NewYork", "item": item, "on_hand": ny_inv})
            inv.append({"day": day, "node": "WarehouseA", "item": item,
                        "on_hand": 200 + day * 5 + (0 if item == "I01" else 10)})
            backlog.append({"day": day, "node": "NewYork", "item": item,
                            "backlog": day * 2 + (0 if item == "I01" else 1)})
            backlog.append({"day": day, "node": "WarehouseA", "item": item, "backlog": 0})
            ship.append({"day": day, "units": 5 + day, "item": item})
    if ship_extra_out_of_window:
        ship.append({"day": 5, "units": 99, "item": "I01"})  # outside window: ignored
    demand_rows = [{"day": d, "item": it, "demand": DEMAND[d][it]} for d in range(6) for it in ITEMS]
    return (
        pd.DataFrame(daily),
        pd.DataFrame(inv),
        pd.DataFrame(backlog),
        pd.DataFrame(ship),
        pd.DataFrame(demand_rows),
    )


def _compute(frames=None):
    daily, inv, backlog, ship, demand = frames or _frames()
    return runner.compute_inventory_metrics(
        daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
    )


class TestDailyAggregation(unittest.TestCase):
    def test_hand_computed_daily_aggregates(self):
        m = _compute()
        # Test demand 126, served 120, unfilled 6, fill 120/126.
        self.assertEqual(m["total_test_demand"], 126)
        self.assertEqual(m["total_served_from_stock"], 120)
        self.assertEqual(m["total_unfilled_demand"], 6)
        self.assertAlmostEqual(m["fill_rate"], 120 / 126)
        # Destination daily sums: 245, 265, 285 -> mean 265, max 285.
        self.assertAlmostEqual(m["average_destination_inventory"], 265)
        self.assertEqual(m["maximum_destination_inventory"], 285)
        # Network daily sums: 675, 705, 735 -> mean 705, max 735.
        self.assertAlmostEqual(m["average_total_network_inventory"], 705)
        self.assertEqual(m["maximum_total_network_inventory"], 735)
        # Backlog daily sums: 9, 13, 17 -> mean 13, max 17, final 17.
        self.assertAlmostEqual(m["average_destination_backlog"], 13)
        self.assertEqual(m["maximum_destination_backlog"], 17)
        self.assertEqual(m["final_destination_backlog"], 17)
        # Shipments: (7+7)+(8+8)+(9+9) = 48; the day-5 row (99) is out of window.
        self.assertEqual(m["total_shipment_units_test_window"], 48)
        self.assertEqual(m["aggregation_version"], runner.INVENTORY_METRICS_VERSION)

    def test_corrected_values_differ_from_old_per_row_definitions(self):
        # The old (superseded) definitions were per-row means and
        # single-record maxima: dest mean 132.5, dest max 145, backlog
        # mean 6.5, backlog max 9, network mean 176.25, network max 230.
        # The corrected daily aggregates are different quantities.
        m = _compute()
        self.assertNotAlmostEqual(m["average_destination_inventory"], 132.5)
        self.assertNotEqual(m["maximum_destination_inventory"], 145)
        self.assertNotAlmostEqual(m["average_destination_backlog"], 6.5)
        self.assertNotEqual(m["maximum_destination_backlog"], 9)
        self.assertNotAlmostEqual(m["average_total_network_inventory"], 176.25)
        self.assertNotEqual(m["maximum_total_network_inventory"], 230)

    def test_maximum_backlog_ranking_is_definition_sensitive(self):
        # Model X: one spike (100 on one item, one day), daily sums 100/0/0.
        # Model Y: steady 60+60 every day, daily sums 120/120/120.
        # Per-row max: X 100 > Y 60  -> Y ranks better (lower max).
        # Daily-aggregate max: X 100 < Y 120 -> X ranks better. RANKING FLIPS.
        # This proves the ranking under the corrected definition can
        # differ from the ranking under the old definition; it does not
        # by itself show whether the thesis ranking flips (daily records
        # for the thesis are unavailable).
        def backlog_frames(newyork_values):
            daily, inv, backlog, ship = [], [], [], []
            for day in range(2, 5):
                for item in ITEMS:
                    daily.append({"day": day, "item": item, "demand": 10,
                                  "served_from_stock": 10, "new_backlog_today": 0})
                    inv.append({"day": day, "node": "NewYork", "item": item, "on_hand": 100})
                    inv.append({"day": day, "node": "WarehouseA", "item": item, "on_hand": 100})
                    backlog.append({"day": day, "node": "NewYork", "item": item,
                                    "backlog": newyork_values[(day, item)]})
                    backlog.append({"day": day, "node": "WarehouseA", "item": item, "backlog": 0})
                    ship.append({"day": day, "units": 1, "item": item})
            demand = pd.DataFrame(
                [{"day": d, "item": it, "demand": 10} for d in range(2, 5) for it in ITEMS]
            )
            return (pd.DataFrame(daily), pd.DataFrame(inv), pd.DataFrame(backlog),
                    pd.DataFrame(ship), demand)

        x_values = {(2, "I01"): 100, (2, "I02"): 0, (3, "I01"): 0, (3, "I02"): 0,
                    (4, "I01"): 0, (4, "I02"): 0}
        y_values = {(d, it): 60 for d in range(2, 5) for it in ITEMS}
        mx = _compute(backlog_frames(x_values))
        my = _compute(backlog_frames(y_values))
        self.assertEqual(mx["maximum_destination_backlog"], 100)
        self.assertEqual(my["maximum_destination_backlog"], 120)
        # Daily-aggregate ordering: X < Y.
        self.assertLess(mx["maximum_destination_backlog"], my["maximum_destination_backlog"])
        # Per-row ordering (old definition): X 100 > Y 60.
        per_row_x = max(x_values.values())
        per_row_y = max(y_values.values())
        self.assertGreater(per_row_x, per_row_y)


class TestValidation(unittest.TestCase):
    def test_identity_violation_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        daily.loc[(daily["day"] == 2) & (daily["item"] == "I01"), "served_from_stock"] -= 1
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_missing_interior_day_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        daily = daily[~((daily["day"] == 3) & (daily["item"] == "I01"))]
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_duplicate_inventory_row_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        inv = pd.concat([inv, inv.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_extra_day_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        extra = {"day": 5, "item": "I01", "demand": 20, "served_from_stock": 20, "new_backlog_today": 0}
        daily = pd.concat([daily, pd.DataFrame([extra])], ignore_index=True)
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_item_set_mismatch_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        extra = {"day": 2, "item": "I03", "demand": 1, "served_from_stock": 1, "new_backlog_today": 0}
        daily = pd.concat([daily, pd.DataFrame([extra])], ignore_index=True)
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_frozen_demand_mismatch_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        demand.loc[(demand["day"] == 2) & (demand["item"] == "I01"), "demand"] += 1
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )

    def test_nonfinite_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        inv = inv.copy()
        inv["on_hand"] = inv["on_hand"].astype(float)
        inv.loc[0, "on_hand"] = float("inf")
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )
        daily2, inv2, backlog2, ship2, demand2 = _frames()
        daily2 = daily2.copy()
        daily2["served_from_stock"] = daily2["served_from_stock"].astype(float)
        daily2.loc[0, "served_from_stock"] = float("nan")
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily2, inv2, backlog2, ship2, {"NewYork"}, demand2, TEST_START, TEST_END
            )

    def test_negative_shipments_rejected(self):
        daily, inv, backlog, ship, demand = _frames()
        ship.loc[0, "units"] = -1
        with self.assertRaises(ValueError):
            runner.compute_inventory_metrics(
                daily, inv, backlog, ship, {"NewYork"}, demand, TEST_START, TEST_END
            )


class TestRankingDirections(unittest.TestCase):
    def _outcomes(self):
        # Model A is best on every metric by direction: smallest on all
        # lower-better metrics, largest on fill_rate.
        rows = []
        for model, fill, unf in [("Seasonal Naive", 0.9, 100.0),
                                 ("ETS", 0.8, 200.0),
                                 ("LightGBM", 0.7, 300.0)]:
            i = ["Seasonal Naive", "ETS", "LightGBM"].index(model)
            rows.append({
                "horizon_days": 2000, "scenario": "normal", "model": model,
                "test_start": 1500, "test_end": 1999,
                "total_test_demand": 126.0, "total_served_from_stock": 120.0,
                "total_unfilled_demand": unf, "fill_rate": fill,
                "average_destination_inventory": 50.0 + 10.0 * i,
                "maximum_destination_inventory": 60.0 + 10.0 * i,
                "average_total_network_inventory": 500.0 + 100.0 * i,
                "maximum_total_network_inventory": 600.0 + 100.0 * i,
                "average_destination_backlog": 5.0 + i,
                "maximum_destination_backlog": 10.0 + 10.0 * i,
                "final_destination_backlog": 3.0 + i,
                "total_shipment_units_test_window": 40.0 + 10.0 * i,
                "aggregation_version": runner.INVENTORY_METRICS_VERSION,
            })
        return pd.DataFrame(rows)

    def test_rank_direction_for_every_metric(self):
        ranked = runner.rank_inventory_metrics(self._outcomes())
        # Every metric must rank Seasonal Naive 1, ETS 2, LightGBM 3.
        for metric in runner.INVENTORY_RANK_DIRECTIONS:
            sub = ranked[ranked["metric"] == metric]
            ranks = dict(zip(sub["model"], sub["rank"]))
            self.assertEqual(
                ranks,
                {"Seasonal Naive": 1.0, "ETS": 2.0, "LightGBM": 3.0},
                f"wrong ranks for {metric} (direction {runner.INVENTORY_RANK_DIRECTIONS[metric]})",
            )
        self.assertEqual(len(ranked), 10 * 3)  # 10 metrics x 3 models
        self.assertEqual(set(runner.INVENTORY_RANK_DIRECTIONS), set(ranked["metric"].unique().tolist()))

    def test_ties_get_average_ranks(self):
        df = self._outcomes()
        # Tie ETS and LightGBM on total_unfilled_demand (both 200).
        df.loc[df["model"] == "LightGBM", "total_unfilled_demand"] = 200.0
        ranked = runner.rank_inventory_metrics(df)
        sub = ranked[ranked["metric"] == "total_unfilled_demand"]
        ranks = dict(zip(sub["model"], sub["rank"]))
        # SN 100 -> 1; ETS/LGBM tied at 200 -> (2+3)/2 = 2.5 each.
        self.assertEqual(ranks, {"Seasonal Naive": 1.0, "ETS": 2.5, "LightGBM": 2.5})


class TestForecastMetricsMASE(unittest.TestCase):
    def test_zero_mase_denominator_recorded_as_nan(self):
        # Exactly 7-periodic training series -> zero denominator.
        # Demand constant 100 for all days; test window 10..12.
        cfg = {"VALIDATION_END": 9, "TEST_START": 10, "TEST_END": 12}
        demand_rows = [{"day": d, "item": it, "demand": 100}
                       for d in range(13) for it in ITEMS]
        demand_df = pd.DataFrame(demand_rows)
        fc_rows = [{"model": m, "item": it, "day": d, "forecast": 100.0, "actual": 100.0}
                   for m in runner.MODELS for it in ITEMS for d in range(10, 13)]
        item_metrics, _ = runner.forecast_metrics(pd.DataFrame(fc_rows), demand_df, cfg)
        self.assertTrue(item_metrics["MASE"].isna().all())
        self.assertTrue((item_metrics["MAE"] == 0.0).all())
    def test_manifest_fields(self):
        manifest = runner.build_run_manifest(
            Path("/tmp/out"), [2000], ["normal"], "completed",
            started_at="2026-01-01T00:00:00+00:00", completed_at="2026-01-01T01:00:00+00:00",
        )
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["seed"], 2025)
        self.assertEqual(manifest["inventory_metrics_version"], runner.INVENTORY_METRICS_VERSION)
        self.assertEqual(manifest["models"], list(runner.MODELS))
        self.assertIn("2000", manifest["horizons"])
        self.assertEqual(manifest["horizons"]["2000"]["TEST_START"], 1500)
        self.assertIn("numpy", manifest["dependency_versions"])
        self.assertIn("lightgbm", manifest["dependency_versions"])
        self.assertEqual(manifest["started_at_utc"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(manifest["completed_at_utc"], "2026-01-01T01:00:00+00:00")
        self.assertEqual(manifest["output_dir"], "/tmp/out")

    def test_check_output_dir(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # Nonexistent: OK.
            runner.check_output_dir(base / "new", False)
            # Empty: OK.
            empty = base / "empty"
            empty.mkdir()
            runner.check_output_dir(empty, False)
            # Non-empty without overwrite: refused.
            nonempty = base / "nonempty"
            nonempty.mkdir()
            (nonempty / "file.txt").write_text("x")
            with self.assertRaises(SystemExit):
                runner.check_output_dir(nonempty, False)
            # Non-empty with overwrite: OK.
            runner.check_output_dir(nonempty, True)


class TestAggregateValidation(unittest.TestCase):
    def _outcomes(self, test_demands=(126, 126, 126)):
        rows = []
        for model, td in zip(runner.MODELS, test_demands):
            rows.append({
                "horizon_days": 2000, "scenario": "normal", "model": model,
                "test_start": 1500, "test_end": 1999,
                "total_test_demand": td, "total_served_from_stock": 120.0,
                "total_unfilled_demand": 6.0, "fill_rate": 120.0 / 126.0,
                "average_destination_inventory": 265.0, "maximum_destination_inventory": 285.0,
                "average_total_network_inventory": 705.0, "maximum_total_network_inventory": 735.0,
                "average_destination_backlog": 13.0, "maximum_destination_backlog": 17.0,
                "final_destination_backlog": 17.0, "total_shipment_units_test_window": 48.0,
                "aggregation_version": runner.INVENTORY_METRICS_VERSION,
            })
        return pd.DataFrame(rows)

    def test_valid_outcomes_pass(self):
        runner.validate_inventory_outcomes(self._outcomes())

    def test_mismatched_test_demand_across_models_rejected(self):
        with self.assertRaises(ValueError):
            runner.validate_inventory_outcomes(self._outcomes((126, 126, 127)))

    def test_identity_violation_rejected(self):
        df = self._outcomes()
        df.loc[0, "total_unfilled_demand"] = 7.0
        with self.assertRaises(ValueError):
            runner.validate_inventory_outcomes(df)

    def test_wrong_version_rejected(self):
        df = self._outcomes()
        df.loc[0, "aggregation_version"] = "inventory-metrics-v1-per-row"
        with self.assertRaises(ValueError):
            runner.validate_inventory_outcomes(df)

    def test_forecast_coverage(self):
        rows = []
        for model in runner.MODELS:
            for item in ITEMS:
                for day in range(1500, 2000):
                    rows.append({"horizon_days": 2000, "scenario": "normal", "model": model,
                                 "item": item, "day": day, "forecast": 1.0, "actual": 2.0})
        df = pd.DataFrame(rows)
        runner.validate_forecast_coverage([df], [2000])
        # Missing one interior day.
        df2 = df[~((df["model"] == "ETS") & (df["item"] == "I01") & (df["day"] == 1750))]
        with self.assertRaises(ValueError):
            runner.validate_forecast_coverage([df2], [2000])
        # Duplicate row.
        df3 = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            runner.validate_forecast_coverage([df3], [2000])
        # Non-finite forecast.
        df4 = df.copy()
        df4.loc[0, "forecast"] = float("inf")
        with self.assertRaises(ValueError):
            runner.validate_forecast_coverage([df4], [2000])


if __name__ == "__main__":
    unittest.main()
