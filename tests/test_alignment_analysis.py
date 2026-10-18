"""Synthetic tests for scripts/alignment_analysis.py.

All inputs are hand-constructed synthetic values with independently
hand-computed expectations. No test uses real experiment outputs, and no
test asserts any thesis result. Passing tests verify the SCRIPT's logic,
not the thesis.

Run: python -m unittest discover -s tests -v   (from the stage-1 directory)
"""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alignment_analysis as aa

MODELS = ["Seasonal Naive", "ETS", "LightGBM"]


def _forecast_item_df(rows):
    """rows: list of (model, item, MAE, RMSE, MASE)."""
    return pd.DataFrame(
        [
            {
                "horizon_days": 2000,
                "scenario": "normal",
                "model": m,
                "item": it,
                "MAE": mae,
                "RMSE": rmse,
                "MASE": mase,
            }
            for (m, it, mae, rmse, mase) in rows
        ]
    )


def _inventory_df(rows, test_start=0, test_end=2):
    """rows: list of dicts with model + the 6 primary metric values."""
    out = []
    for r in rows:
        d = {
            "horizon_days": 2000,
            "scenario": "normal",
            "test_start": test_start,
            "test_end": test_end,
        }
        d.update(r)
        out.append(d)
    return pd.DataFrame(out)


class TestRankDirections(unittest.TestCase):
    def test_forecast_rank_ascending_and_inventory_directions(self):
        # Two items per model; means are the per-model values below.
        item_rows = []
        for m, mae, rmse, mase in [
            ("Seasonal Naive", 10.0, 12.0, 1.0),
            ("ETS", 20.0, 22.0, 2.0),
            ("LightGBM", 30.0, 32.0, 3.0),
        ]:
            for item in ("I01", "I02"):
                item_rows.append((m, item, mae, rmse, mase))
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        mae_ranks = dict(
            zip(
                fr[fr["metric"] == "MAE"]["model"],
                fr[fr["metric"] == "MAE"]["rank"],
            )
        )
        self.assertEqual(mae_ranks, {"Seasonal Naive": 1.0, "ETS": 2.0, "LightGBM": 3.0})

        inv = _inventory_df(
            [
                {
                    "model": "Seasonal Naive",
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                },
                {
                    "model": "ETS",
                    "fill_rate": 0.8,
                    "total_unfilled_demand": 200.0,
                    "average_destination_inventory": 40.0,
                    "average_destination_backlog": 4.0,
                    "maximum_destination_backlog": 40.0,
                    "average_total_network_inventory": 400.0,
                },
                {
                    "model": "LightGBM",
                    "fill_rate": 0.7,
                    "total_unfilled_demand": 300.0,
                    "average_destination_inventory": 60.0,
                    "average_destination_backlog": 6.0,
                    "maximum_destination_backlog": 60.0,
                    "average_total_network_inventory": 600.0,
                },
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        fill = dict(
            zip(ir[ir["metric"] == "fill_rate"]["model"], ir[ir["metric"] == "fill_rate"]["rank"])
        )
        # Higher fill rate ranks first.
        self.assertEqual(fill, {"Seasonal Naive": 1.0, "ETS": 2.0, "LightGBM": 3.0})
        dest = dict(
            zip(
                ir[ir["metric"] == "average_destination_inventory"]["model"],
                ir[ir["metric"] == "average_destination_inventory"]["rank"],
            )
        )
        # Lower inventory ranks first: ETS 40 -> 1, SN 50 -> 2, LGBM 60 -> 3.
        self.assertEqual(dest, {"Seasonal Naive": 2.0, "ETS": 1.0, "LightGBM": 3.0})

    def test_ties_get_average_ranks(self):
        item_rows = []
        for m, mae in [("Seasonal Naive", 10.0), ("ETS", 10.0), ("LightGBM", 30.0)]:
            item_rows.append((m, "I01", mae, mae, mae))
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        mae_ranks = dict(
            zip(
                fr[fr["metric"] == "MAE"]["model"],
                fr[fr["metric"] == "MAE"]["rank"],
            )
        )
        # Tied for best -> (1+2)/2 = 1.5 each.
        self.assertEqual(mae_ranks, {"Seasonal Naive": 1.5, "ETS": 1.5, "LightGBM": 3.0})


class TestDeltaAndAgreement(unittest.TestCase):
    def test_delta_exact_and_summary(self):
        # Forecast ranks 1,2,3 (SN, ETS, LGBM); inventory ranks 3,2,1.
        item_rows = []
        for m, mae in [("Seasonal Naive", 10.0), ("ETS", 20.0), ("LightGBM", 30.0)]:
            item_rows.append((m, "I01", mae, mae, mae))
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        inv = _inventory_df(
            [
                {
                    "model": "Seasonal Naive",
                    "fill_rate": 0.7,
                    "total_unfilled_demand": 300.0,
                    "average_destination_inventory": 60.0,
                    "average_destination_backlog": 6.0,
                    "maximum_destination_backlog": 60.0,
                    "average_total_network_inventory": 600.0,
                },
                {
                    "model": "ETS",
                    "fill_rate": 0.8,
                    "total_unfilled_demand": 200.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                },
                {
                    "model": "LightGBM",
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 40.0,
                    "average_destination_backlog": 4.0,
                    "maximum_destination_backlog": 40.0,
                    "average_total_network_inventory": 400.0,
                },
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        aligned = aa.align(fr, ir)
        # Focus on MAE x fill_rate: forecast ranks (1,2,3), fill ranks (3,2,1).
        # Reindex to the fixed model order (alphabetical sort would reorder).
        sub = (
            aligned[
                (aligned["forecast_metric"] == "MAE")
                & (aligned["inventory_metric"] == "fill_rate")
            ]
            .set_index("model")
            .loc[MODELS]
            .reset_index()
        )
        self.assertEqual(list(sub["forecast_rank"]), [1.0, 2.0, 3.0])
        self.assertEqual(list(sub["inventory_rank"]), [3.0, 2.0, 1.0])
        self.assertEqual(list(sub["rank_difference"]), [2.0, 0.0, -2.0])
        self.assertEqual(list(sub["abs_rank_difference"]), [2.0, 0.0, 2.0])
        self.assertEqual(list(sub["exact_agreement"]), [False, True, False])
        # Per-combination descriptive correlations for a full reversal.
        self.assertTrue(math.isclose(sub["spearman_rho_descriptive"].iloc[0], -1.0))
        self.assertTrue(math.isclose(sub["kendall_tau_b_descriptive"].iloc[0], -1.0))
        # Summary: complete-ordering agreement is False for this combination.
        summary = aa.summarize(aligned, ir)
        self.assertEqual(summary["n_model_rows"], len(aligned))
        self.assertIn("complete_ordering_agreement_share", summary)
        self.assertIn("model_level_exact_agreement_share", summary)
        # No inferential statistics may appear as computed fields. (The
        # caveats text mentions p-values only to state they are NOT
        # computed, so check keys, not prose substrings.)
        forbidden_keys = {"p_value", "pvalue", "p-value", "confidence_interval",
                          "confidence", "std_error", "standard_error", "se", "ci"}
        def _check_keys(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    self.assertNotIn(k, forbidden_keys)
                    _check_keys(v)
            elif isinstance(obj, list):
                for v in obj:
                    _check_keys(v)
        _check_keys(summary)
        self.assertTrue(
            any("No confidence intervals" in c for c in summary["caveats"])
        )


class TestCorrelationsN3(unittest.TestCase):
    def test_spearman_kendall_known_values(self):
        # Identical orderings.
        self.assertTrue(math.isclose(aa.spearman_rho([1, 2, 3], [1, 2, 3]), 1.0))
        self.assertTrue(math.isclose(aa.kendall_tau_b([1, 2, 3], [1, 2, 3]), 1.0))
        # Full reversal.
        self.assertTrue(math.isclose(aa.spearman_rho([1, 2, 3], [3, 2, 1]), -1.0))
        self.assertTrue(math.isclose(aa.kendall_tau_b([1, 2, 3], [3, 2, 1]), -1.0))
        # Single adjacent swap: rho = 0.5, tau-b = (2-1)/3 = 1/3 (hand-computed).
        self.assertTrue(math.isclose(aa.spearman_rho([1, 2, 3], [2, 1, 3]), 0.5))
        self.assertTrue(math.isclose(aa.kendall_tau_b([1, 2, 3], [2, 1, 3]), 1.0 / 3.0))

    def test_tied_correlations(self):
        # Tied forecast ranks vs untied inventory ranks: finite, not NaN.
        rho = aa.spearman_rho([1.5, 1.5, 3.0], [1.0, 2.0, 3.0])
        tau = aa.kendall_tau_b([1.5, 1.5, 3.0], [1.0, 2.0, 3.0])
        self.assertTrue(math.isfinite(rho))
        self.assertTrue(math.isfinite(tau))


class TestRedundancyAndSchema(unittest.TestCase):
    def test_fill_unfilled_ranks_identical(self):
        # fill_rate = 1 - unfilled/demand with common demand 1000.
        inv = _inventory_df(
            [
                {
                    "model": "Seasonal Naive",
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                },
                {
                    "model": "ETS",
                    "fill_rate": 0.8,
                    "total_unfilled_demand": 200.0,
                    "average_destination_inventory": 40.0,
                    "average_destination_backlog": 4.0,
                    "maximum_destination_backlog": 40.0,
                    "average_total_network_inventory": 400.0,
                },
                {
                    "model": "LightGBM",
                    "fill_rate": 0.7,
                    "total_unfilled_demand": 300.0,
                    "average_destination_inventory": 60.0,
                    "average_destination_backlog": 6.0,
                    "maximum_destination_backlog": 60.0,
                    "average_total_network_inventory": 600.0,
                },
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        check = aa.check_fill_unfilled_redundancy(ir)
        self.assertEqual(check["share_agreeing"], 1.0)
        self.assertEqual(check["disagreeing_groups"], [])

    def test_rejects_missing_column(self):
        bad = pd.DataFrame([{"horizon_days": 2000, "scenario": "normal", "model": "ETS"}])
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(bad)
        with self.assertRaises(ValueError):
            aa.compute_inventory_ranks(bad)

    def test_rejects_mismatched_item_sets(self):
        rows = [
            ("Seasonal Naive", "I01", 10.0, 10.0, 10.0),
            ("Seasonal Naive", "I02", 10.0, 10.0, 10.0),
            ("ETS", "I01", 20.0, 20.0, 20.0),
            ("LightGBM", "I01", 30.0, 30.0, 30.0),
        ]
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(_forecast_item_df(rows))

    def test_rejects_mismatched_model_sets(self):
        item_rows = [(m, "I01", 10.0, 10.0, 10.0) for m in MODELS]
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        inv = _inventory_df(
            [
                {
                    "model": "Seasonal Naive",
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                },
                {
                    "model": "ETS",
                    "fill_rate": 0.8,
                    "total_unfilled_demand": 200.0,
                    "average_destination_inventory": 40.0,
                    "average_destination_backlog": 4.0,
                    "maximum_destination_backlog": 40.0,
                    "average_total_network_inventory": 400.0,
                },
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        with self.assertRaises(ValueError):
            aa.align(fr, ir)


class TestNoHardcodedOutcomes(unittest.TestCase):
    def test_script_computes_from_inputs_not_constants(self):
        # Two different synthetic datasets must give different outputs.
        def run(mae_values, fill_values):
            item_rows = [
                (m, "I01", mae, mae, mae) for m, mae in zip(MODELS, mae_values)
            ]
            fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
            inv = _inventory_df(
                [
                    {
                        "model": m,
                        "fill_rate": f,
                        "total_unfilled_demand": (1.0 - f) * 1000.0,
                        "average_destination_inventory": 50.0,
                        "average_destination_backlog": 5.0,
                        "maximum_destination_backlog": 50.0,
                        "average_total_network_inventory": 500.0,
                    }
                    for m, f in zip(MODELS, fill_values)
                ]
            )
            ir = aa.compute_inventory_ranks(inv)
            aligned = aa.align(fr, ir)
            return aa.summarize(aligned, ir)

        s1 = run([10.0, 20.0, 30.0], [0.9, 0.8, 0.7])
        s2 = run([30.0, 20.0, 10.0], [0.9, 0.8, 0.7])
        self.assertNotEqual(
            s1["complete_ordering_agreement_share"],
            s2["complete_ordering_agreement_share"],
        )

    def test_script_contains_no_locked_table_numbers(self):
        # Guard: the implementation must not contain thesis result values.
        # (These literals live in this TEST as forbidden strings, not as
        # outcomes used by the script.)
        script = (Path(__file__).resolve().parents[1] / "scripts" / "alignment_analysis.py").read_text()
        for forbidden in ["0.999209", "16461523", "0.999708", "87816644", "101932845"]:
            self.assertNotIn(forbidden, script)


class TestEndToEndSynthetic(unittest.TestCase):
    def test_main_writes_outputs_on_synthetic_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item_rows = []
            for m, mae in [("Seasonal Naive", 10.0), ("ETS", 20.0), ("LightGBM", 30.0)]:
                for item in ("I01", "I02"):
                    item_rows.append(
                        {
                            "horizon_days": 2000,
                            "scenario": "normal",
                            "model": m,
                            "item": item,
                            "MAE": mae,
                            "RMSE": mae,
                            "MASE": mae / 10.0,
                        }
                    )
            pd.DataFrame(item_rows).to_csv(tmp / "forecast_item.csv", index=False)
            inv_rows = []
            # Every inventory metric is constructed to give the same ordering
            # as the forecast (SN best, ETS middle, LGBM worst), so every
            # combination must agree completely.
            inv_by_model = {
                "Seasonal Naive": (0.9, 100.0, 40.0, 4.0, 40.0, 400.0),
                "ETS": (0.8, 200.0, 50.0, 5.0, 50.0, 500.0),
                "LightGBM": (0.7, 300.0, 60.0, 6.0, 60.0, 600.0),
            }
            for m, (fill, unf, dinv, dback, mback, ninv) in inv_by_model.items():
                inv_rows.append(
                    {
                        "horizon_days": 2000,
                        "scenario": "normal",
                        "model": m,
                        "test_start": 0,
                        "test_end": 2,
                        "fill_rate": fill,
                        "total_unfilled_demand": unf,
                        "average_destination_inventory": dinv,
                        "average_destination_backlog": dback,
                        "maximum_destination_backlog": mback,
                        "average_total_network_inventory": ninv,
                    }
                )
            pd.DataFrame(inv_rows).to_csv(tmp / "inventory.csv", index=False)
            # Day-level forecasts covering EXACTLY the test window [0, 2],
            # for both items present in the item metrics.
            forecast_rows = [
                {
                    "horizon_days": 2000,
                    "scenario": "normal",
                    "model": m,
                    "item": item,
                    "day": day,
                    "forecast": 10.0,
                    "actual": 10.0,
                }
                for m in MODELS
                for item in ("I01", "I02")
                for day in (0, 1, 2)
            ]
            pd.DataFrame(forecast_rows).to_csv(tmp / "forecasts.csv", index=False)
            out = tmp / "out"
            sys.argv = [
                "alignment_analysis.py",
                "--forecast-item-metrics",
                str(tmp / "forecast_item.csv"),
                "--forecasts",
                str(tmp / "forecasts.csv"),
                "--inventory-outcomes",
                str(tmp / "inventory.csv"),
                "--expected-horizons",
                "2000",
                "--expected-scenarios",
                "normal",
                "--output-dir",
                str(out),
            ]
            aa.main()
            results = pd.read_csv(out / "alignment_results.csv")
            # 1 horizon x 1 scenario x 3 forecast metrics x 6 inventory metrics x 3 models = 54 rows.
            self.assertEqual(len(results), 54)
            summary = json.loads((out / "alignment_summary.json").read_text())
            self.assertEqual(summary["n_combinations"], 18)
            self.assertEqual(summary["n_model_rows"], 54)
            # Forecast and inventory orderings are identical here, so every
            # combination agrees completely and every delta is 0.
            self.assertEqual(summary["complete_ordering_agreement_share"], 1.0)
            self.assertEqual(summary["mean_abs_rank_difference"], 0.0)
            # Sensitivity summary excludes one redundant metric: 15 combinations.
            sens = summary["sensitivity_excluding_total_unfilled_demand"]
            self.assertEqual(sens["n_combinations"], 15)
            self.assertIn("sensitivity analysis", sens["label"])


class TestItemSetValidation(unittest.TestCase):
    def test_rejects_duplicate_item_records(self):
        rows = [
            ("Seasonal Naive", "I01", 10.0, 10.0, 10.0),
            ("Seasonal Naive", "I01", 10.0, 10.0, 10.0),  # duplicate
            ("ETS", "I01", 20.0, 20.0, 20.0),
            ("LightGBM", "I01", 30.0, 30.0, 30.0),
        ]
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(_forecast_item_df(rows))

    def test_rejects_same_count_different_item_sets(self):
        # Equal counts (2 each) but different item-ID sets: SN {I01, I02},
        # ETS {I01, I03}. Counts alone would pass; sets must be compared.
        rows = [
            ("Seasonal Naive", "I01", 10.0, 10.0, 10.0),
            ("Seasonal Naive", "I02", 10.0, 10.0, 10.0),
            ("ETS", "I01", 20.0, 20.0, 20.0),
            ("ETS", "I03", 20.0, 20.0, 20.0),
            ("LightGBM", "I01", 30.0, 30.0, 30.0),
            ("LightGBM", "I02", 30.0, 30.0, 30.0),
        ]
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(_forecast_item_df(rows))

    def test_accepts_identical_item_sets(self):
        rows = []
        for m, mae in [("Seasonal Naive", 10.0), ("ETS", 20.0), ("LightGBM", 30.0)]:
            for item in ("I01", "I02"):
                rows.append((m, item, mae, mae, mae))
        fr = aa.compute_forecast_ranks(_forecast_item_df(rows))
        self.assertEqual(len(fr), 9)  # 3 models x 3 metrics


class TestModelSetValidation(unittest.TestCase):
    def _ranks_for(self, models):
        fr_rows = []
        ir_rows = []
        for i, m in enumerate(models):
            fr_rows.append((m, "I01", 10.0 * (i + 1), 10.0 * (i + 1), 10.0 * (i + 1)))
            ir_rows.append(
                {
                    "model": m,
                    "fill_rate": 0.9 - 0.1 * i,
                    "total_unfilled_demand": 100.0 * (i + 1),
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                }
            )
        return (
            aa.compute_forecast_ranks(_forecast_item_df(fr_rows)),
            aa.compute_inventory_ranks(_inventory_df(ir_rows)),
        )

    def test_rejects_both_missing_same_model(self):
        # Both inputs missing Seasonal Naive: previously this passed the
        # equality check (both sets equal); now it must be rejected.
        fr, ir = self._ranks_for(["ETS", "LightGBM"])
        with self.assertRaises(ValueError):
            aa.align(fr, ir)

    def test_rejects_extra_model(self):
        fr, ir = self._ranks_for(["Seasonal Naive", "ETS", "LightGBM", "Extra"])
        with self.assertRaises(ValueError):
            aa.align(fr, ir)

    def test_accepts_exact_three_models(self):
        fr, ir = self._ranks_for(["Seasonal Naive", "ETS", "LightGBM"])
        aligned = aa.align(fr, ir)
        self.assertEqual(len(aligned), 54)  # 3 forecast x 6 inventory x 3 models

    def test_custom_expected_models(self):
        fr, ir = self._ranks_for(["A", "B"])
        aligned = aa.align(fr, ir, expected_models=("A", "B"))
        self.assertEqual(len(aligned), 36)  # 3 forecast x 6 inventory x 2 models
        with self.assertRaises(ValueError):
            aa.align(fr, ir, expected_models=("A", "B", "C"))


class TestWindowValidation(unittest.TestCase):
    def _outcomes(self, test_start=0, test_end=2):
        return _inventory_df(
            [
                {
                    "model": m,
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                }
                for m in MODELS
            ],
            test_start=test_start,
            test_end=test_end,
        )

    def _forecasts(self, days_per_model):
        rows = []
        for m, days in zip(MODELS, days_per_model):
            for day in days:
                rows.append(
                    {
                        "horizon_days": 2000,
                        "scenario": "normal",
                        "model": m,
                        "item": "I01",
                        "day": day,
                    }
                )
        return pd.DataFrame(rows)

    def test_accepts_exact_window_coverage(self):
        aa.validate_forecast_window(
            self._forecasts([(0, 1, 2)] * 3), self._outcomes(0, 2)
        )

    def test_rejects_forecast_day_before_window(self):
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(
                self._forecasts([(-1, 0, 1, 2), (0, 1, 2), (0, 1, 2)]),
                self._outcomes(0, 2),
            )

    def test_rejects_forecast_day_after_window(self):
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(
                self._forecasts([(0, 1, 2, 3), (0, 1, 2), (0, 1, 2)]),
                self._outcomes(0, 2),
            )

    def test_rejects_subset_coverage(self):
        # Days inside the window but not covering it fully: not comparable.
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(
                self._forecasts([(0, 1), (0, 1, 2), (0, 1, 2)]),
                self._outcomes(0, 2),
            )

    def test_rejects_missing_interior_day_all_items(self):
        # Endpoint checks alone would pass (min 0, max 2); day 1 is missing.
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(
                self._forecasts([(0, 2)] * 3), self._outcomes(0, 2)
            )

    def test_rejects_missing_interior_day_one_item(self):
        # One item missing day 1 while the other item is complete.
        rows = []
        for m in MODELS:
            for item, days in (("I01", (0, 1, 2)), ("I02", (0, 2) if m == "Seasonal Naive" else (0, 1, 2))):
                for day in days:
                    rows.append(
                        {
                            "horizon_days": 2000,
                            "scenario": "normal",
                            "model": m,
                            "item": item,
                            "day": day,
                        }
                    )
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(pd.DataFrame(rows), self._outcomes(0, 2))

    def test_rejects_duplicate_item_day_row(self):
        forecasts = self._forecasts([(0, 1, 2)] * 3)
        forecasts = pd.concat([forecasts, forecasts.iloc[[0]]], ignore_index=True)
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(forecasts, self._outcomes(0, 2))

    def test_rejects_different_test_windows_across_models(self):
        # Each model's forecasts match its OWN window, so per-model checks
        # alone would pass; the common-window check must fail.
        outcomes = pd.DataFrame(
            [
                {
                    "horizon_days": 2000,
                    "scenario": "normal",
                    "model": m,
                    "test_start": start,
                    "test_end": end,
                    "fill_rate": 0.9,
                    "total_unfilled_demand": 100.0,
                    "average_destination_inventory": 50.0,
                    "average_destination_backlog": 5.0,
                    "maximum_destination_backlog": 50.0,
                    "average_total_network_inventory": 500.0,
                }
                for m, (start, end) in zip(
                    MODELS, [(0, 2), (1, 3), (0, 2)]
                )
            ]
        )
        forecasts = self._forecasts([(0, 1, 2), (1, 2, 3), (0, 1, 2)])
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(forecasts, outcomes)
        bad = self._forecasts([(0, 1, 2)] * 3).drop(columns=["day"])
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(bad, self._outcomes(0, 2))

    def test_rejects_missing_test_window_metadata(self):
        bad = self._outcomes(0, 2).drop(columns=["test_start"])
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(self._forecasts([(0, 1, 2)] * 3), bad)

    def test_rejects_inverted_test_window(self):
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(
                self._forecasts([(0, 1, 2)] * 3), self._outcomes(2, 0)
            )

    def test_rejects_mismatched_model_sets(self):
        forecasts = self._forecasts([(0, 1, 2)] * 3)
        forecasts = forecasts[forecasts["model"] != "ETS"]
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(forecasts, self._outcomes(0, 2))


class TestForecastItemSets(unittest.TestCase):
    def _forecasts(self, items_per_model):
        rows = []
        for m, items in zip(MODELS, items_per_model):
            for item in items:
                for day in (0, 1, 2):
                    rows.append(
                        {
                            "horizon_days": 2000,
                            "scenario": "normal",
                            "model": m,
                            "item": item,
                            "day": day,
                        }
                    )
        return pd.DataFrame(rows)

    def _item_metrics(self, items_per_model):
        rows = []
        for m, items in zip(MODELS, items_per_model):
            for item in items:
                rows.append((m, item, 10.0, 10.0, 10.0))
        return _forecast_item_df(rows)

    def test_accepts_matching_item_sets(self):
        aa.validate_forecast_item_sets(
            self._forecasts([("I01", "I02")] * 3),
            self._item_metrics([("I01", "I02")] * 3),
        )

    def test_rejects_forecasts_missing_item(self):
        with self.assertRaises(ValueError):
            aa.validate_forecast_item_sets(
                self._forecasts([("I01",)] * 3),
                self._item_metrics([("I01", "I02")] * 3),
            )

    def test_rejects_item_metrics_missing_item(self):
        with self.assertRaises(ValueError):
            aa.validate_forecast_item_sets(
                self._forecasts([("I01", "I02")] * 3),
                self._item_metrics([("I01",)] * 3),
            )


class TestExperimentGrid(unittest.TestCase):
    def _ranks(self, combos):
        rows = []
        for (h, s) in combos:
            for m in MODELS:
                rows.append(
                    {
                        "horizon_days": h,
                        "scenario": s,
                        "model": m,
                        "metric": "MAE",
                        "value": 10.0,
                        "rank": 1.0,
                    }
                )
        return pd.DataFrame(rows)

    def test_accepts_complete_grid(self):
        combos = [(2000, "normal"), (2000, "demand"), (3000, "normal"), (3000, "demand")]
        fr = self._ranks(combos)
        ir = self._ranks(combos)
        aa.validate_experiment_grid(fr, ir, (2000, 3000), ("normal", "demand"))

    def test_rejects_missing_grid_combination(self):
        combos = [(2000, "normal"), (2000, "demand"), (3000, "normal")]
        fr = self._ranks(combos)
        ir = self._ranks(combos)
        with self.assertRaises(ValueError):
            aa.validate_experiment_grid(fr, ir, (2000, 3000), ("normal", "demand"))

    def test_rejects_extra_grid_combination(self):
        combos = [
            (2000, "normal"),
            (2000, "demand"),
            (3000, "normal"),
            (3000, "demand"),
            (5000, "normal"),
        ]
        fr = self._ranks(combos)
        ir = self._ranks(combos)
        with self.assertRaises(ValueError):
            aa.validate_experiment_grid(fr, ir, (2000, 3000), ("normal", "demand"))

    def test_rejects_grid_mismatch_between_inputs(self):
        full = [(2000, "normal"), (2000, "demand"), (3000, "normal"), (3000, "demand")]
        partial = [(2000, "normal"), (2000, "demand"), (3000, "normal")]
        fr = self._ranks(full)
        ir = self._ranks(partial)
        with self.assertRaises(ValueError):
            aa.validate_experiment_grid(fr, ir, (2000, 3000), ("normal", "demand"))


class TestTerminology(unittest.TestCase):
    def test_no_most_preferred_language(self):
        script = (
            Path(__file__).resolve().parents[1] / "scripts" / "alignment_analysis.py"
        ).read_text()
        self.assertNotIn("most preferred", script)
        self.assertNotIn("is preferred", script)
        self.assertIn("direction-oriented rank", script)


class TestSensitivitySummary(unittest.TestCase):
    def test_sensitivity_excludes_one_redundant_metric(self):
        item_rows = [
            (m, "I01", 10.0 * (i + 1), 10.0 * (i + 1), 10.0 * (i + 1))
            for i, m in enumerate(MODELS)
        ]
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        inv = _inventory_df(
            [
                {
                    "model": m,
                    "fill_rate": 0.9 - 0.1 * i,
                    "total_unfilled_demand": 100.0 * (i + 1),
                    "average_destination_inventory": 40.0 + 10.0 * i,
                    "average_destination_backlog": 4.0 + i,
                    "maximum_destination_backlog": 40.0 + 10.0 * i,
                    "average_total_network_inventory": 400.0 + 100.0 * i,
                }
                for i, m in enumerate(MODELS)
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        aligned = aa.align(fr, ir)
        summary = aa.summarize(aligned, ir)
        # Primary: 1 x 1 x 3 forecast x 6 inventory = 18 combinations.
        self.assertEqual(summary["n_combinations"], 18)
        # Sensitivity: 1 x 1 x 3 forecast x 5 inventory = 15 combinations.
        sens = summary["sensitivity_excluding_total_unfilled_demand"]
        self.assertEqual(sens["n_combinations"], 15)
        self.assertIn("sensitivity analysis", sens["label"])
        self.assertNotIn("total_unfilled_demand", sens["by_inventory_metric"])
        # Forecast and inventory orderings agree here, so both shares are 1.
        self.assertEqual(summary["complete_ordering_agreement_share"], 1.0)
        self.assertEqual(sens["complete_ordering_agreement_share"], 1.0)

    def test_excluding_either_redundant_metric_gives_identical_results(self):
        item_rows = [
            (m, "I01", 10.0 * (i + 1), 10.0 * (i + 1), 10.0 * (i + 1))
            for i, m in enumerate(MODELS)
        ]
        fr = aa.compute_forecast_ranks(_forecast_item_df(item_rows))
        inv = _inventory_df(
            [
                {
                    "model": m,
                    "fill_rate": 0.9 - 0.1 * i,
                    "total_unfilled_demand": 100.0 * (i + 1),
                    "average_destination_inventory": 40.0 + 10.0 * i,
                    "average_destination_backlog": 4.0 + i,
                    "maximum_destination_backlog": 40.0 + 10.0 * i,
                    "average_total_network_inventory": 400.0 + 100.0 * i,
                }
                for i, m in enumerate(MODELS)
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        aligned = aa.align(fr, ir)
        summary = aa.summarize(aligned, ir)
        sens_unfilled = summary["sensitivity_excluding_total_unfilled_demand"]
        # Recompute the same summaries excluding fill_rate instead.
        alt = aa._summarize_subset(aligned[aligned["inventory_metric"] != "fill_rate"])
        self.assertEqual(sens_unfilled["n_combinations"], alt["n_combinations"])
        self.assertEqual(
            sens_unfilled["complete_ordering_agreement_share"],
            alt["complete_ordering_agreement_share"],
        )
        self.assertEqual(
            sens_unfilled["mean_abs_rank_difference"],
            alt["mean_abs_rank_difference"],
        )


    def test_main_rejects_incomplete_grid_by_default(self):
        # Single-combination inputs must fail under the default 12-combination
        # grid, proving the grid check runs on every CLI invocation.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            item_rows = []
            for m, mae in [("Seasonal Naive", 10.0), ("ETS", 20.0), ("LightGBM", 30.0)]:
                for item in ("I01", "I02"):
                    item_rows.append(
                        {
                            "horizon_days": 2000,
                            "scenario": "normal",
                            "model": m,
                            "item": item,
                            "MAE": mae,
                            "RMSE": mae,
                            "MASE": mae / 10.0,
                        }
                    )
            pd.DataFrame(item_rows).to_csv(tmp / "forecast_item.csv", index=False)
            inv_rows = []
            for m, fill in [("Seasonal Naive", 0.9), ("ETS", 0.8), ("LightGBM", 0.7)]:
                inv_rows.append(
                    {
                        "horizon_days": 2000,
                        "scenario": "normal",
                        "model": m,
                        "test_start": 0,
                        "test_end": 2,
                        "fill_rate": fill,
                        "total_unfilled_demand": (1.0 - fill) * 1000.0,
                        "average_destination_inventory": 50.0,
                        "average_destination_backlog": 5.0,
                        "maximum_destination_backlog": 50.0,
                        "average_total_network_inventory": 500.0,
                    }
                )
            pd.DataFrame(inv_rows).to_csv(tmp / "inventory.csv", index=False)
            forecast_rows = [
                {
                    "horizon_days": 2000,
                    "scenario": "normal",
                    "model": m,
                    "item": item,
                    "day": day,
                    "forecast": 10.0,
                    "actual": 10.0,
                }
                for m in MODELS
                for item in ("I01", "I02")
                for day in (0, 1, 2)
            ]
            pd.DataFrame(forecast_rows).to_csv(tmp / "forecasts.csv", index=False)
            sys.argv = [
                "alignment_analysis.py",
                "--forecast-item-metrics",
                str(tmp / "forecast_item.csv"),
                "--forecasts",
                str(tmp / "forecasts.csv"),
                "--inventory-outcomes",
                str(tmp / "inventory.csv"),
                "--output-dir",
                str(tmp / "out"),
            ]
            with self.assertRaises(ValueError):
                aa.main()


class TestFiniteValues(unittest.TestCase):
    def test_rejects_inf_forecast_metric(self):
        rows = [
            ("Seasonal Naive", "I01", float("inf"), 10.0, 10.0),
            ("ETS", "I01", 20.0, 20.0, 20.0),
            ("LightGBM", "I01", 30.0, 30.0, 30.0),
        ]
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(_forecast_item_df(rows))

    def test_rejects_nan_inventory_metric(self):
        inv = _inventory_df(
            [
                {"model": "Seasonal Naive", "fill_rate": float("nan"),
                 "total_unfilled_demand": 100.0, "average_destination_inventory": 50.0,
                 "average_destination_backlog": 5.0, "maximum_destination_backlog": 50.0,
                 "average_total_network_inventory": 500.0},
                {"model": "ETS", "fill_rate": 0.8,
                 "total_unfilled_demand": 200.0, "average_destination_inventory": 40.0,
                 "average_destination_backlog": 4.0, "maximum_destination_backlog": 40.0,
                 "average_total_network_inventory": 400.0},
                {"model": "LightGBM", "fill_rate": 0.7,
                 "total_unfilled_demand": 300.0, "average_destination_inventory": 60.0,
                 "average_destination_backlog": 6.0, "maximum_destination_backlog": 60.0,
                 "average_total_network_inventory": 600.0},
            ]
        )
        with self.assertRaises(ValueError):
            aa.compute_inventory_ranks(inv)

    def test_rejects_inf_day_level_forecast(self):
        forecasts = pd.DataFrame(
            [{"horizon_days": 2000, "scenario": "normal", "model": m, "item": "I01",
              "day": d, "forecast": 10.0, "actual": 10.0}
             for m in MODELS for d in (0, 1, 2)]
        )
        forecasts.loc[0, "forecast"] = float("inf")
        outcomes = _inventory_df(
            [{"model": m, "fill_rate": 0.9, "total_unfilled_demand": 100.0,
              "average_destination_inventory": 50.0, "average_destination_backlog": 5.0,
              "maximum_destination_backlog": 50.0, "average_total_network_inventory": 500.0}
             for m in MODELS]
        )
        with self.assertRaises(ValueError):
            aa.validate_forecast_window(forecasts, outcomes)


class TestMedianSensitivity(unittest.TestCase):
    def _skewed_item_df(self):
        # Right-skewed errors for Seasonal Naive: item MAEs [10, 10, 100]
        # -> mean 40, median 10. ETS [20, 20, 20] -> mean = median = 20.
        # LightGBM [30, 30, 30] -> mean = median = 30.
        # Mean ordering: ETS (1), LightGBM (2), Seasonal Naive (3).
        # Median ordering: Seasonal Naive (1), ETS (2), LightGBM (3).
        rows = []
        for m, vals in [("Seasonal Naive", [10.0, 10.0, 100.0]),
                        ("ETS", [20.0, 20.0, 20.0]),
                        ("LightGBM", [30.0, 30.0, 30.0])]:
            for item, v in zip(("I01", "I02", "I03"), vals):
                rows.append((m, item, v, v, v))
        return _forecast_item_df(rows)

    def test_median_ranks_differ_from_mean_ranks(self):
        fr_mean = aa.compute_forecast_ranks(self._skewed_item_df(), aggregation="mean")
        fr_median = aa.compute_forecast_ranks(self._skewed_item_df(), aggregation="median")
        mean_ranks = dict(zip(
            fr_mean[fr_mean["metric"] == "MAE"]["model"],
            fr_mean[fr_mean["metric"] == "MAE"]["rank"],
        ))
        median_ranks = dict(zip(
            fr_median[fr_median["metric"] == "MAE"]["model"],
            fr_median[fr_median["metric"] == "MAE"]["rank"],
        ))
        self.assertEqual(mean_ranks, {"Seasonal Naive": 3.0, "ETS": 1.0, "LightGBM": 2.0})
        self.assertEqual(median_ranks, {"Seasonal Naive": 1.0, "ETS": 2.0, "LightGBM": 3.0})
        self.assertEqual(set(fr_median["aggregation"].unique().tolist()), {"median"})
        self.assertEqual(set(fr_mean["aggregation"].unique().tolist()), {"mean"})

    def test_invalid_aggregation_rejected(self):
        with self.assertRaises(ValueError):
            aa.compute_forecast_ranks(self._skewed_item_df(), aggregation="trimmed")

    def test_median_sensitivity_summary(self):
        # Inventory ranks: Seasonal Naive 1, ETS 2, LightGBM 3 on every metric.
        inv = _inventory_df(
            [
                {"model": "Seasonal Naive", "fill_rate": 0.9, "total_unfilled_demand": 100.0,
                 "average_destination_inventory": 50.0, "average_destination_backlog": 5.0,
                 "maximum_destination_backlog": 50.0, "average_total_network_inventory": 500.0},
                {"model": "ETS", "fill_rate": 0.8, "total_unfilled_demand": 200.0,
                 "average_destination_inventory": 60.0, "average_destination_backlog": 6.0,
                 "maximum_destination_backlog": 60.0, "average_total_network_inventory": 600.0},
                {"model": "LightGBM", "fill_rate": 0.7, "total_unfilled_demand": 300.0,
                 "average_destination_inventory": 70.0, "average_destination_backlog": 7.0,
                 "maximum_destination_backlog": 70.0, "average_total_network_inventory": 700.0},
            ]
        )
        ir = aa.compute_inventory_ranks(inv)
        aligned = aa.align(aa.compute_forecast_ranks(self._skewed_item_df(), aggregation="mean"), ir)
        median_aligned = aa.align(aa.compute_forecast_ranks(self._skewed_item_df(), aggregation="median"), ir)
        summary = aa.summarize(aligned, ir, median_aligned=median_aligned)
        # Mean-aligned: per combination |Delta| = 2, 1, 1 -> mean 4/3.
        self.assertAlmostEqual(summary["mean_abs_rank_difference"], 4 / 3)
        # Median-aligned: forecast and inventory orderings agree -> 0.
        med = summary["sensitivity_median_forecast_ranks"]
        self.assertAlmostEqual(med["mean_abs_rank_difference"], 0.0)
        self.assertEqual(med["complete_ordering_agreement_share"], 1.0)
        self.assertIn("MEDIAN-of-item", med["label"])


class TestBreakdownSummaries(unittest.TestCase):
    def test_horizon_and_scenario_breakdowns(self):
        # Horizon 2000: forecast and inventory orderings agree (all Delta = 0).
        # Horizon 3000: forecast ordering reversed (A 3, B 2, C 1) vs
        # inventory (A 1, B 2, C 3) -> |Delta| = 2, 0, 2 per combination.
        item_rows = []
        for horizon, order in ((2000, [10.0, 20.0, 30.0]), (3000, [30.0, 20.0, 10.0])):
            for m, v in zip(MODELS, order):
                for item in ("I01", "I02"):
                    item_rows.append({
                        "horizon_days": horizon, "scenario": "normal", "model": m,
                        "item": item, "MAE": v, "RMSE": v, "MASE": v,
                    })
        item_df = pd.DataFrame(item_rows)
        inv_rows = []
        for horizon in (2000, 3000):
            for m, fill in zip(MODELS, (0.9, 0.8, 0.7)):
                inv_rows.append({
                    "horizon_days": horizon, "scenario": "normal", "model": m,
                    "test_start": 0, "test_end": 2, "fill_rate": fill,
                    "total_unfilled_demand": 100.0 * (MODELS.index(m) + 1),
                    "average_destination_inventory": 50.0 + 10.0 * MODELS.index(m),
                    "average_destination_backlog": 5.0 + MODELS.index(m),
                    "maximum_destination_backlog": 50.0 + 10.0 * MODELS.index(m),
                    "average_total_network_inventory": 500.0 + 100.0 * MODELS.index(m),
                })
        ir = aa.compute_inventory_ranks(pd.DataFrame(inv_rows))
        aligned = aa.align(aa.compute_forecast_ranks(item_df), ir)
        summary = aa.summarize(aligned, ir)
        # 2 horizons x 1 scenario x 3 forecast x 6 inventory x 3 models = 108 rows.
        self.assertEqual(summary["n_model_rows"], 108)
        # Overall mean |Delta| = (0*54 + (4/3)*54) / 108 = 2/3.
        self.assertAlmostEqual(summary["mean_abs_rank_difference"], 2 / 3)
        by_h = summary["by_horizon"]
        self.assertEqual(by_h["2000"]["n_model_rows"], 54)
        self.assertEqual(by_h["2000"]["n_combinations"], 18)
        self.assertAlmostEqual(by_h["2000"]["mean_abs_rank_difference"], 0.0)
        self.assertEqual(by_h["3000"]["n_model_rows"], 54)
        self.assertAlmostEqual(by_h["3000"]["mean_abs_rank_difference"], 4 / 3)
        by_s = summary["by_scenario"]
        self.assertEqual(by_s["normal"]["n_model_rows"], 108)
        self.assertAlmostEqual(by_s["normal"]["mean_abs_rank_difference"], 2 / 3)
        # Denominator-weighted means reproduce the overall mean.
        weighted_h = sum(v["mean_abs_rank_difference"] * v["n_model_rows"] for v in by_h.values()) / 108
        weighted_s = sum(v["mean_abs_rank_difference"] * v["n_model_rows"] for v in by_s.values()) / 108
        self.assertAlmostEqual(weighted_h, summary["mean_abs_rank_difference"])
        self.assertAlmostEqual(weighted_s, summary["mean_abs_rank_difference"])


class TestItemMetricCrossCheck(unittest.TestCase):
    def test_matching_item_metrics_pass(self):
        forecasts = pd.DataFrame([
            {"horizon_days": 2000, "scenario": "normal", "model": m, "item": it,
             "day": d, "forecast": 10.0, "actual": 12.0}
            for m in MODELS for it in ("I01",) for d in (0, 1, 2)
        ])
        # Errors all 2 -> MAE 2, RMSE 2.
        item_metrics = pd.DataFrame([
            {"horizon_days": 2000, "scenario": "normal", "model": m, "item": "I01",
             "MAE": 2.0, "RMSE": 2.0, "MASE": 1.0}
            for m in MODELS
        ])
        notes = aa._verify_item_metrics_against_forecasts(forecasts, item_metrics)
        self.assertTrue(any("passed" in n for n in notes), notes)

    def test_mismatched_item_metric_noted(self):
        forecasts = pd.DataFrame([
            {"horizon_days": 2000, "scenario": "normal", "model": "ETS", "item": "I01",
             "day": d, "forecast": 10.0, "actual": 12.0}
            for d in (0, 1, 2)
        ])
        item_metrics = pd.DataFrame([
            {"horizon_days": 2000, "scenario": "normal", "model": "ETS", "item": "I01",
             "MAE": 5.0, "RMSE": 2.0, "MASE": 1.0}
        ])
        notes = aa._verify_item_metrics_against_forecasts(forecasts, item_metrics)
        self.assertTrue(any("mismatch" in n and "MAE" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
