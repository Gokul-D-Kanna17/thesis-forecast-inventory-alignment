"""F05 tests: recompute_forecast_metrics on SYNTHETIC fixtures only.

Hand-computed fixture: items I01/I02, train days 0..9 (train_end=9),
test days 10..12. Demand:
  I01: 100 + day            -> train denom mean|train[7:]-train[:-7]| = 7
  I02: 50 + 2*day + day%3   -> train denom = (15+15+12)/3 = 14
Test actuals: I01 (110,111,112); I02 (71,74,74).
Forecasts:
  Seasonal Naive: I01 errors (2,2,2); I02 errors (0,4,0)
    -> per-item MAE (2, 4/3); RMSE (2, sqrt(16/3)); MASE (2/7, (4/3)/14)
    -> summary MAE 5/3, RMSE (2+sqrt(16/3))/2, MASE (2/7+(4/3)/14)/2
  ETS: errors 1 everywhere -> MAE 1, RMSE 1, MASE (1/7+1/14)/2
  LightGBM: perfect -> 0, 0, 0
The SN fixture separates mean-of-item RMSE/MASE from pooled values.
"""

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import recompute_forecast_metrics as f05  # noqa: E402

ITEMS = ["I01", "I02"]
TRAIN_END, TEST_START, TEST_END = 9, 10, 12
SCENARIO = "normal"


def _demand(day, item):
    if item == "I01":
        return 100 + day
    return 50 + 2 * day + (day % 3)


def _forecast(model, item, day):
    actual = _demand(day, item)
    if model == "Seasonal Naive":
        if item == "I01":
            return actual - 2
        return {10: 71, 11: 70, 12: 74}[day]  # errors (0,4,0)
    if model == "ETS":
        return actual - 1
    return actual  # LightGBM perfect


def _write_demand(base: Path) -> Path:
    rows = [{"day": d, "item": it, "demand": _demand(d, it)}
            for d in range(0, TEST_END + 1) for it in ITEMS]
    p = base / "demand.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return p


def _write_forecasts(base: Path, fmt: str):
    """Return [(path, format)] in the requested format."""
    if fmt == "runner":
        rows = [{"model": m, "item": it, "day": d,
                 "forecast": _forecast(m, it, d), "actual": _demand(d, it)}
                for m in f05.EXPECTED_MODELS for it in ITEMS
                for d in range(TEST_START, TEST_END + 1)]
        p = base / "forecasts.csv"
        pd.DataFrame(rows).to_csv(p, index=False)
        return [(p, "runner")]
    if fmt == "notebook_per_row":
        rows = [{"item": it, "model": m, "split": "test", "day": d,
                 "actual": _demand(d, it), "forecast": _forecast(m, it, d)}
                for m in f05.EXPECTED_MODELS for it in ITEMS
                for d in range(TEST_START, TEST_END + 1)]
        p = base / "test_forecasts.csv"
        pd.DataFrame(rows).to_csv(p, index=False)
        return [(p, "notebook_per_row")]
    if fmt == "notebook_demand":
        files = []
        for m, fname in (("Seasonal Naive", "seasonal_naive_test.csv"),
                         ("ETS", "ets_test.csv"),
                         ("LightGBM", "lightgbm_test.csv")):
            rows = [{"item": it, "day": d,
                     "forecast": _forecast(m, it, d), "actual": _demand(d, it)}
                    for it in ITEMS for d in range(TEST_START, TEST_END + 1)]
            p = base / fname
            pd.DataFrame(rows).to_csv(p, index=False)
            files.append((p, "notebook_demand"))
        return files
    raise ValueError(fmt)


def _recompute(base: Path, fmt: str, **kw):
    demand = _write_demand(base)
    return f05.recompute(_write_forecasts(base, fmt), demand, SCENARIO,
                         TRAIN_END, TEST_START, TEST_END, **kw)


class TestF05(unittest.TestCase):
    def test_happy_path_runner_format(self):
        with tempfile.TemporaryDirectory() as td:
            out = _recompute(Path(td), "runner")
        per_item = out["per_item"]
        sn_i01 = per_item[(per_item["model"] == "Seasonal Naive") & (per_item["item"] == "I01")].iloc[0]
        self.assertAlmostEqual(sn_i01["MAE"], 2.0)
        self.assertAlmostEqual(sn_i01["RMSE"], 2.0)
        self.assertAlmostEqual(sn_i01["MASE"], 2 / 7)
        sn_i02 = per_item[(per_item["model"] == "Seasonal Naive") & (per_item["item"] == "I02")].iloc[0]
        self.assertAlmostEqual(sn_i02["MAE"], 4 / 3)
        self.assertAlmostEqual(sn_i02["RMSE"], math.sqrt(16 / 3))
        self.assertAlmostEqual(sn_i02["MASE"], (4 / 3) / 14)
        summary = out["summary"]
        sn = summary[summary["model"] == "Seasonal Naive"].iloc[0]
        self.assertAlmostEqual(sn["mean_MAE"], 5 / 3)
        self.assertAlmostEqual(sn["mean_RMSE"], (2 + math.sqrt(16 / 3)) / 2)
        self.assertAlmostEqual(sn["mean_MASE"], (2 / 7 + (4 / 3) / 14) / 2)
        ets = summary[summary["model"] == "ETS"].iloc[0]
        self.assertAlmostEqual(ets["mean_MAE"], 1.0)
        self.assertAlmostEqual(ets["mean_RMSE"], 1.0)
        self.assertAlmostEqual(ets["mean_MASE"], (1 / 7 + 1 / 14) / 2)
        lgb = summary[summary["model"] == "LightGBM"].iloc[0]
        self.assertAlmostEqual(lgb["mean_MAE"], 0.0)
        self.assertAlmostEqual(lgb["mean_RMSE"], 0.0)
        self.assertAlmostEqual(lgb["mean_MASE"], 0.0)
        self.assertIn("aggregation", out["metadata"]["definitions"])
        self.assertIn("mean across items", out["metadata"]["definitions"]["aggregation"])

    def test_mean_of_item_not_pooled(self):
        # Pooled SN RMSE = sqrt(28/6) = 2.1602; mean-of-item RMSE = 2.1547.
        # Pooled SN MASE (pooled MAE / mean denom) = 0.1587; mean-of-item = 0.1905.
        with tempfile.TemporaryDirectory() as td:
            out = _recompute(Path(td), "runner")
        sn = out["summary"][out["summary"]["model"] == "Seasonal Naive"].iloc[0]
        pooled_rmse = math.sqrt(28 / 6)
        pooled_mase = (5 / 3) / ((7 + 14) / 2)
        self.assertNotAlmostEqual(sn["mean_RMSE"], pooled_rmse, places=3)
        self.assertNotAlmostEqual(sn["mean_MASE"], pooled_mase, places=3)
        self.assertAlmostEqual(sn["mean_RMSE"], (2 + math.sqrt(16 / 3)) / 2)
        self.assertAlmostEqual(sn["mean_MASE"], (2 / 7 + (4 / 3) / 14) / 2)

    def test_adapter_notebook_per_row(self):
        with tempfile.TemporaryDirectory() as td:
            out = _recompute(Path(td), "notebook_per_row")
        sn = out["summary"][out["summary"]["model"] == "Seasonal Naive"].iloc[0]
        self.assertAlmostEqual(sn["mean_MAE"], 5 / 3)

    def test_adapter_notebook_per_row_split_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "notebook_per_row")
            df = pd.read_csv(files[0][0])
            df.loc[0, "split"] = "validation"
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_adapter_notebook_demand(self):
        with tempfile.TemporaryDirectory() as td:
            out = _recompute(Path(td), "notebook_demand")
        sn = out["summary"][out["summary"]["model"] == "Seasonal Naive"].iloc[0]
        self.assertAlmostEqual(sn["mean_MAE"], 5 / 3)
        ets = out["summary"][out["summary"]["model"] == "ETS"].iloc[0]
        self.assertAlmostEqual(ets["mean_MASE"], (1 / 7 + 1 / 14) / 2)

    def test_adapter_notebook_demand_unknown_filename_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "notebook_demand")
            renamed = base / "weird_name.csv"
            files[0][0].rename(renamed)
            files[0] = (renamed, "notebook_demand")
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_nonfinite_forecast_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            demand = _write_demand(base)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            df["forecast"] = df["forecast"].astype(float)
            df.loc[0, "forecast"] = float("inf")
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, demand, SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_nonfinite_actual_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            demand = _write_demand(base)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            df["actual"] = df["actual"].astype(float)
            df.loc[0, "actual"] = float("nan")
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, demand, SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_nonfinite_demand_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            demand = _write_demand(base)
            df = pd.read_csv(demand)
            df["demand"] = df["demand"].astype(float)
            df.loc[0, "demand"] = float("inf")
            df.to_csv(demand, index=False)
            with self.assertRaises(ValueError):
                f05.recompute(_write_forecasts(base, "runner"), demand,
                              SCENARIO, TRAIN_END, TEST_START, TEST_END)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            pd.concat([df, df.iloc[[0]]], ignore_index=True).to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_missing_interior_day_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            df = df[~((df["model"] == "ETS") & (df["item"] == "I01") & (df["day"] == 11))]
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_item_set_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            df = df[~((df["model"] == "ETS") & (df["item"] == "I02"))]
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_actual_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "runner")
            df = pd.read_csv(files[0][0])
            df.loc[0, "actual"] += 1
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, _write_demand(base), SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_zero_mase_denominator_rejected(self):
        # Training series exactly 7-periodic: denom = 0 -> MASE undefined.
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            demand_rows = [{"day": d, "item": it, "demand": 100 + (d % 7)}
                           for d in range(0, TEST_END + 1) for it in ITEMS]
            demand_path = base / "demand.csv"
            pd.DataFrame(demand_rows).to_csv(demand_path, index=False)
            files = _write_forecasts(base, "runner")
            # Align forecast actuals with the periodic demand on test days.
            df = pd.read_csv(files[0][0])
            df["actual"] = df.apply(lambda r: 100 + (r["day"] % 7), axis=1)
            df["forecast"] = df["actual"]
            df.to_csv(files[0][0], index=False)
            with self.assertRaises(ValueError):
                f05.recompute(files, demand_path, SCENARIO, TRAIN_END, TEST_START, TEST_END)

    def test_train_end_before_test_start_required(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with self.assertRaises(ValueError):
                f05.recompute(_write_forecasts(base, "runner"), _write_demand(base),
                              SCENARIO, TEST_START, TEST_START, TEST_END)

    def test_discrepancy_report(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            locked = pd.DataFrame([
                {"scenario": SCENARIO, "model": "Seasonal Naive", "MAE": 5 / 3,
                 "RMSE": 2.1547, "MASE": 0.1905, "source": "locked"},
                {"scenario": SCENARIO, "model": "ETS", "MAE": 1.0, "RMSE": 1.0,
                 "MASE": 0.5, "source": "slides"},
            ])
            locked_path = base / "locked.csv"
            locked.to_csv(locked_path, index=False)
            out = f05.recompute(_write_forecasts(base, "runner"), _write_demand(base),
                                SCENARIO, TRAIN_END, TEST_START, TEST_END, locked_path)
        disc = out["discrepancy"]
        sn_mae = disc[(disc["model"] == "Seasonal Naive") & (disc["metric"] == "MAE")].iloc[0]
        self.assertEqual(sn_mae["status"], "match")
        sn_mase = disc[(disc["model"] == "Seasonal Naive") & (disc["metric"] == "MASE")].iloc[0]
        self.assertEqual(sn_mase["status"], "differ")
        self.assertAlmostEqual(sn_mase["difference"], (2 / 7 + (4 / 3) / 14) / 2 - 0.1905)
        ets_mase = disc[(disc["model"] == "ETS") & (disc["metric"] == "MASE")].iloc[0]
        self.assertEqual(ets_mase["status"], "differ")
        lgb = disc[disc["model"] == "LightGBM"]
        self.assertTrue((lgb["status"] == "cannot-check").all())

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            files = _write_forecasts(base, "runner")
            demand = _write_demand(base)
            locked = pd.DataFrame([{"scenario": SCENARIO, "model": "Seasonal Naive",
                                    "MAE": 5 / 3, "RMSE": 2.1547, "MASE": 0.1905, "source": "locked"}])
            locked_path = base / "locked.csv"
            locked.to_csv(locked_path, index=False)
            out_dir = base / "out"
            proc = subprocess.run(
                [sys.executable, "-m", "recompute_forecast_metrics",
                 "--forecast-file", str(files[0][0]), "--forecast-format", "runner",
                 "--demand-file", str(demand), "--scenario", SCENARIO,
                 "--train-end", str(TRAIN_END), "--test-start", str(TEST_START),
                 "--test-end", str(TEST_END), "--locked-values", str(locked_path),
                 "--output-dir", str(out_dir)],
                cwd=str(Path(__file__).resolve().parent.parent / "scripts"),
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for name in ("recomputed_forecast_metrics_per_item.csv",
                         "recomputed_forecast_metrics_summary.csv",
                         "recomputed_forecast_metadata.json",
                         "discrepancy_report.csv"):
                self.assertTrue((out_dir / name).exists(), name)
            summary = pd.read_csv(out_dir / "recomputed_forecast_metrics_summary.csv")
            self.assertEqual(len(summary), 3)
            meta = json.loads((out_dir / "recomputed_forecast_metadata.json").read_text())
            self.assertEqual(meta["definitions"]["aggregation"][:4], "mean")


if __name__ == "__main__":
    unittest.main()


class TestNoLockedNumbers(unittest.TestCase):
    def test_script_contains_no_locked_table_numbers(self):
        """The recomputation must derive values from inputs, never embed locked/slide outcomes."""
        script = (
            Path(__file__).resolve().parent.parent
            / "scripts" / "recompute_forecast_metrics.py"
        ).read_text()
        for literal in ("17.3824", "26.689412", "0.999708", "20.772073", "22.134175", "0.816538"):
            self.assertNotIn(literal, script, f"locked/slide number {literal} in F05 script")
