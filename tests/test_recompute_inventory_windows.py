"""F01 tests: recompute_inventory_windows on SYNTHETIC fixtures only.

No thesis results are produced here. Fixtures are hand-computed small
tables (2 items, 6 days, test window 2..4, 2 nodes, 2 models) with
expected values derived by hand in the comments below.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import recompute_inventory_windows as f01  # noqa: E402

ITEMS = ["I01", "I02"]
NODES = ["NewYork", "WarehouseA"]
DAYS = list(range(6))
TEST_START, TEST_END = 2, 4

# Frozen demand: demand[day][item]
DEMAND = {
    0: {"I01": 10, "I02": 20},
    1: {"I01": 12, "I02": 22},
    2: {"I01": 14, "I02": 24},
    3: {"I01": 16, "I02": 26},
    4: {"I01": 18, "I02": 28},
    5: {"I01": 20, "I02": 30},
}
# Test demand = (14+24)+(16+26)+(18+28) = 126. Full = 240.

# Per-model profile: (newyork_base, warehouse_base, backlog_slope, ship_base)
PROFILES = {
    "Seasonal Naive": (100, 200, 2, 5),
    "ETS": (90, 190, 3, 4),
}


def _model_rows(profile):
    ny_base, wh_base, bl_slope, ship_base = profile
    daily_rows, inv_rows, backlog_rows, ship_rows = [], [], [], []
    for day in DAYS:
        for item in ITEMS:
            off = 0 if item == "I01" else 5
            demand = DEMAND[day][item]
            unfilled = 1 if (TEST_START <= day <= TEST_END) else 0
            if profile is PROFILES["ETS"]:
                unfilled = 2 * unfilled
            served = demand - unfilled
            ny_inv = ny_base + day * 10 + off
            daily_rows.append({
                "day": day, "item": item, "demand": demand,
                "served_from_stock": served, "new_backlog_today": unfilled,
                "dest_on_hand_end_before_ship": ny_inv,
                "dest_backlog_end_before_ship": day * bl_slope + (0 if item == "I01" else 1),
            })
            inv_rows.append({"day": day, "node": "NewYork", "item": item, "on_hand": ny_inv})
            inv_rows.append({"day": day, "node": "WarehouseA", "item": item,
                             "on_hand": wh_base + day * 5 + (0 if item == "I01" else 10)})
            backlog_rows.append({"day": day, "node": "NewYork", "item": item,
                                 "backlog": day * bl_slope + (0 if item == "I01" else 1)})
            backlog_rows.append({"day": day, "node": "WarehouseA", "item": item, "backlog": 0})
            ship_rows.append({
                "day": day, "arrival_day": day + 2, "from": "WarehouseA", "to": "NewYork",
                "item": item, "units": ship_base + day,
                "path_nodes": "WarehouseA>NewYork", "edge_times": 2.0,
            })
    # Sort by the keys the script expects (already in order, but explicit).
    daily_rows.sort(key=lambda r: (r["day"], r["item"]))
    inv_rows.sort(key=lambda r: (r["day"], r["node"], r["item"]))
    backlog_rows.sort(key=lambda r: (r["day"], r["node"], r["item"]))
    ship_rows.sort(key=lambda r: (r["day"], r["arrival_day"], r["from"], r["to"], r["item"]))
    return daily_rows, inv_rows, backlog_rows, ship_rows


def _write_fixture(base: Path, mutate=None):
    """Write a synthetic manifest + files. mutate(manifest, files) may corrupt it."""
    demand_rows = [
        {"day": d, "item": it, "demand": DEMAND[d][it]} for d in DAYS for it in ITEMS
    ]
    demand_path = base / "demand.csv"
    pd.DataFrame(demand_rows).to_csv(demand_path, index=False)
    models = []
    for model, profile in PROFILES.items():
        mdir = base / model.replace(" ", "_").lower()
        mdir.mkdir(parents=True, exist_ok=True)
        daily, inv, backlog, ship = _model_rows(profile)
        pd.DataFrame(daily).to_csv(mdir / "daily_records.csv", index=False)
        pd.DataFrame(inv).to_csv(mdir / "inventory_history.csv", index=False)
        pd.DataFrame(backlog).to_csv(mdir / "backlog_history.csv", index=False)
        pd.DataFrame(ship).to_csv(mdir / "shipments.csv", index=False)
        models.append({"model": model, "inventory_dir": str(mdir)})
    manifest = {"scenarios": [{"scenario": "normal", "demand_file": str(demand_path), "models": models}]}
    files = {
        "demand": demand_path,
        "daily_SN": base / "seasonal_naive" / "daily_records.csv",
        "daily_ETS": base / "ets" / "daily_records.csv",
        "inv_SN": base / "seasonal_naive" / "inventory_history.csv",
        "ship_SN": base / "seasonal_naive" / "shipments.csv",
    }
    if mutate:
        mutate(manifest, files)
    return manifest


def _run(manifest, chunksize=2):
    return f01.recompute_from_manifest(manifest, TEST_START, TEST_END, "NewYork", chunksize)


class TestF01(unittest.TestCase):
    def test_happy_path_hand_computed(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td))
            results, meta = _run(manifest)
        self.assertEqual(len(results), 2)
        sn = results[results["model"] == "Seasonal Naive"].iloc[0]
        ets = results[results["model"] == "ETS"].iloc[0]
        # Seasonal Naive: test demand 126, unfilled 6 (1 x 6 pairs), served 120.
        self.assertEqual(sn["test_demand"], 126)
        self.assertEqual(sn["test_served"], 120)
        self.assertAlmostEqual(sn["fill_rate"], 120 / 126)
        self.assertEqual(sn["total_unfilled_demand"], 6)
        # DAILY AGGREGATES (v2). NewYork daily totals: 245, 265, 285
        # (sum across items per day) -> mean 265, max 285, final 285.
        self.assertAlmostEqual(sn["average_destination_inventory"], 265)
        self.assertEqual(sn["maximum_destination_inventory"], 285)
        self.assertEqual(sn["final_destination_backlog"], 17)
        # Network daily totals: 675, 705, 735 -> mean 705, max 735.
        self.assertAlmostEqual(sn["average_total_network_inventory"], 705)
        self.assertEqual(sn["maximum_total_network_inventory"], 735)
        # NewYork backlog daily totals: 9, 13, 17 -> mean 13, max 17.
        self.assertAlmostEqual(sn["average_destination_backlog"], 13)
        self.assertEqual(sn["maximum_destination_backlog"], 17)
        # Shipments test window: (7+7)+(8+8)+(9+9) = 48.
        self.assertEqual(sn["total_shipment_units_test_window"], 48)
        # Full-horizon demand is reported separately, never the denominator.
        self.assertEqual(sn["full_horizon_demand"], 240)
        self.assertAlmostEqual(sn["fill_rate"], 120 / 126)
        self.assertNotAlmostEqual(sn["fill_rate"], 120 / 240)
        # ETS: unfilled 12, served 114; NewYork daily 225/245/265 -> mean 245,
        # max 265; network daily 635/665/695 -> mean 665, max 695;
        # backlog daily 13/19/25 -> mean 19, max 25, final 25; ships 42.
        self.assertEqual(ets["total_unfilled_demand"], 12)
        self.assertAlmostEqual(ets["fill_rate"], 114 / 126)
        self.assertAlmostEqual(ets["average_destination_inventory"], 245)
        self.assertEqual(ets["maximum_destination_inventory"], 265)
        self.assertEqual(ets["final_destination_backlog"], 25)
        self.assertAlmostEqual(ets["average_total_network_inventory"], 665)
        self.assertEqual(ets["maximum_total_network_inventory"], 695)
        self.assertAlmostEqual(ets["average_destination_backlog"], 19)
        self.assertEqual(ets["maximum_destination_backlog"], 25)
        self.assertEqual(ets["total_shipment_units_test_window"], 42)
        # Aggregation version is recorded on every row.
        self.assertEqual(sn["aggregation_version"], "inventory-metrics-v2-daily-aggregate")
        # Metadata carries definitions + validation + provenance.
        self.assertIn("definitions", meta)
        self.assertIn("fill_rate", meta["definitions"])
        self.assertTrue(meta["validation"])

    def test_duplicate_daily_row_rejected(self):
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            pd.concat([df, df.iloc[[3]]], ignore_index=True).to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_missing_interior_day_rejected(self):
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            df = df[~((df["day"] == 3) & (df["item"] == "I01"))]
            df.to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_item_set_mismatch_rejected(self):
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            df = df[df["item"] == "I01"]  # drop I02 from one model's inventory
            df.to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_demand_mismatch_rejected(self):
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            df.loc[(df["day"] == 2) & (df["item"] == "I01"), "demand"] += 1
            df.to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_unsorted_daily_rejected(self):
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            df.iloc[::-1].to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_missing_file_rejected(self):
        def mutate(manifest, files):
            files["ship_SN"].unlink()
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(FileNotFoundError):
                _run(manifest)

    def test_fill_rate_identity_violation_rejected(self):
        # served + unfilled != demand for one row (identity fails, demand unchanged).
        def mutate(manifest, files):
            df = pd.read_csv(files["daily_SN"])
            df.loc[(df["day"] == 2) & (df["item"] == "I01"), "new_backlog_today"] += 2
            df.to_csv(files["daily_SN"], index=False)
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td), mutate)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_destination_node_param_honoured(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = _write_fixture(Path(td))
            results, _ = f01.recompute_from_manifest(manifest, TEST_START, TEST_END, "WarehouseA", 2)
        sn = results[results["model"] == "Seasonal Naive"].iloc[0]
        # WarehouseA as "destination": daily totals 430, 440, 450 -> mean 440, max 450.
        self.assertAlmostEqual(sn["average_destination_inventory"], 440)
        self.assertEqual(sn["maximum_destination_inventory"], 450)
        self.assertEqual(sn["final_destination_backlog"], 0)

    def test_maximum_backlog_ranking_is_definition_sensitive(self):
        # Model X: one spike (100 on one item, one day), daily sums 100/0/0.
        # Model Y: steady 60+60 every day, daily sums 120/120/120.
        # Per-row max: X 100 > Y 60 -> Y ranks better (lower max).
        # Daily-aggregate max: X 100 < Y 120 -> X ranks better. RANKING FLIPS.
        # This proves the ranking under the corrected definition can
        # differ from the ranking under the old definition; it does not
        # by itself show whether the thesis ranking flips (daily records
        # for the thesis are unavailable).
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            demand_rows = [{"day": d, "item": it, "demand": 10}
                           for d in range(6) for it in ITEMS]
            demand_path = base / "demand.csv"
            pd.DataFrame(demand_rows).to_csv(demand_path, index=False)
            profiles = {
                "Spike": {(2, "I01"): 100, (2, "I02"): 0, (3, "I01"): 0,
                          (3, "I02"): 0, (4, "I01"): 0, (4, "I02"): 0},
                "Steady": {(d, it): 60 for d in range(2, 5) for it in ITEMS},
            }
            models = []
            for model, bl in profiles.items():
                mdir = base / model.lower()
                mdir.mkdir()
                daily = [{"day": d, "item": it, "demand": 10, "served_from_stock": 10,
                          "new_backlog_today": 0, "dest_on_hand_end_before_ship": 100,
                          "dest_backlog_end_before_ship": 0} for d in range(6) for it in ITEMS]
                pd.DataFrame(daily).sort_values(["day", "item"]).to_csv(mdir / "daily_records.csv", index=False)
                inv = [{"day": d, "node": n, "item": it, "on_hand": 100}
                       for d in range(6) for n in NODES for it in ITEMS]
                pd.DataFrame(inv).sort_values(["day", "node", "item"]).to_csv(mdir / "inventory_history.csv", index=False)
                bl_rows = []
                for d in range(6):
                    for n in NODES:
                        for it in ITEMS:
                            v = bl.get((d, it), 0) if n == "NewYork" else 0
                            bl_rows.append({"day": d, "node": n, "item": it, "backlog": v})
                pd.DataFrame(bl_rows).sort_values(["day", "node", "item"]).to_csv(mdir / "backlog_history.csv", index=False)
                ship = [{"day": d, "arrival_day": d + 1, "from": "WarehouseA", "to": "NewYork",
                         "item": it, "units": 1, "path_nodes": "X", "edge_times": 1.0}
                        for d in range(6) for it in ITEMS]
                pd.DataFrame(ship).sort_values(["day", "arrival_day", "from", "to", "item"]).to_csv(mdir / "shipments.csv", index=False)
                models.append({"model": model, "inventory_dir": str(mdir)})
            manifest = {"scenarios": [{"scenario": "normal", "demand_file": str(demand_path), "models": models}]}
            results, _ = f01.recompute_from_manifest(manifest, TEST_START, TEST_END, "NewYork", 2)
        x = results[results["model"] == "Spike"].iloc[0]
        y = results[results["model"] == "Steady"].iloc[0]
        # Daily-aggregate maxima: X 100 < Y 120.
        self.assertEqual(x["maximum_destination_backlog"], 100)
        self.assertEqual(y["maximum_destination_backlog"], 120)
        self.assertLess(x["maximum_destination_backlog"], y["maximum_destination_backlog"])

    def test_forecast_crosscheck(self):
        # Matching forecast actuals pass; mismatched actuals fail.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = _write_fixture(base)
            fc_rows = [
                {"day": d, "item": it, "forecast": 1, "actual": DEMAND[d][it]}
                for d in DAYS for it in ITEMS
            ]
            fc_path = base / "forecast.csv"
            pd.DataFrame(fc_rows).to_csv(fc_path, index=False)
            manifest["scenarios"][0]["forecast_file"] = str(fc_path)
            results, _ = _run(manifest)
            self.assertEqual(len(results), 2)
            # Mismatch: bump one test-day actual.
            fc_rows[4]["actual"] += 1
            pd.DataFrame(fc_rows).to_csv(fc_path, index=False)
            with self.assertRaises(ValueError):
                _run(manifest)

    def test_multidigit_day_sorting(self):
        # Days 8..12: numeric sort must not be confused by lexicographic
        # day strings ("10" < "2"). A lexicographic check would falsely fail.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            days = list(range(13))  # 0..12; frozen demand starts at 0 (real files do)
            demand_rows = [{"day": d, "item": it, "demand": 10} for d in days for it in ITEMS]
            demand_path = base / "demand.csv"
            pd.DataFrame(demand_rows).to_csv(demand_path, index=False)
            mdir = base / "seasonal_naive"
            mdir.mkdir()
            daily = [{"day": d, "item": it, "demand": 10, "served_from_stock": 10,
                      "new_backlog_today": 0, "dest_on_hand_end_before_ship": 100,
                      "dest_backlog_end_before_ship": 0} for d in days for it in ITEMS]
            pd.DataFrame(daily).sort_values(["day", "item"]).to_csv(mdir / "daily_records.csv", index=False)
            inv = [{"day": d, "node": n, "item": it, "on_hand": 100}
                   for d in days for n in NODES for it in ITEMS]
            pd.DataFrame(inv).sort_values(["day", "node", "item"]).to_csv(mdir / "inventory_history.csv", index=False)
            bl = [{"day": d, "node": n, "item": it, "backlog": 0}
                  for d in days for n in NODES for it in ITEMS]
            pd.DataFrame(bl).sort_values(["day", "node", "item"]).to_csv(mdir / "backlog_history.csv", index=False)
            ship = [{"day": d, "arrival_day": d + 1, "from": "WarehouseA", "to": "NewYork",
                     "item": it, "units": 1, "path_nodes": "X", "edge_times": 1.0}
                    for d in days for it in ITEMS]
            pd.DataFrame(ship).sort_values(["day", "arrival_day", "from", "to", "item"]).to_csv(mdir / "shipments.csv", index=False)
            manifest = {"scenarios": [{"scenario": "normal", "demand_file": str(demand_path),
                                        "models": [{"model": "Seasonal Naive", "inventory_dir": str(mdir)}]}]}
            results, _ = f01.recompute_from_manifest(manifest, 10, 11, "NewYork", 2)
            self.assertEqual(results.iloc[0]["test_demand"], 40)  # 2 days x 2 items x 10

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            manifest = _write_fixture(base)
            manifest_path = base / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            out_dir = base / "out"
            proc = subprocess.run(
                [sys.executable, "-m", "recompute_inventory_windows",
                 "--manifest", str(manifest_path), "--output-dir", str(out_dir),
                 "--test-start", str(TEST_START), "--test-end", str(TEST_END)],
                cwd=str(Path(__file__).resolve().parent.parent / "scripts"),
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((out_dir / "recomputed_inventory_outcomes.csv").exists())
            self.assertTrue((out_dir / "recomputed_inventory_metadata.json").exists())
            results = pd.read_csv(out_dir / "recomputed_inventory_outcomes.csv")
            self.assertEqual(len(results), 2)
            self.assertIn("full_horizon_demand", results.columns)


if __name__ == "__main__":
    unittest.main()


class TestNoLockedNumbers(unittest.TestCase):
    def test_script_contains_no_locked_table_numbers(self):
        """The recomputation must derive values from inputs, never embed locked outcomes."""
        script = (
            Path(__file__).resolve().parent.parent
            / "scripts" / "recompute_inventory_windows.py"
        ).read_text()
        for literal in ("11899428", "17182745", "0.999209", "87816644", "335681841"):
            self.assertNotIn(literal, script, f"locked-table number {literal} in F01 script")
