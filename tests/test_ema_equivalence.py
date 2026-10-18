"""F04 — EMA injection equivalence test (compensation vs hold).

Verifies that the two forecast-injection methods used in the thesis produce
equivalent simulator decisions under matched inputs, using the ACTUAL
simulator implementation and the ACTUAL injection methods from the thesis
code — not a reimplementation of the EMA formula in isolation.

Sources (read before writing this test; wrappers below are verbatim copies
of the thesis code, adapted only in that the forecast/demand lookups are
passed explicitly instead of being closed over):
- Simulator EMA update: Supplychaingeo_item50.py, step() stage 4 (L435-437):
      demand_ema[iid] = ema_alpha * dq + (1 - ema_alpha) * demand_ema[iid]
  demand_ema is read ONLY in step() stage 5, AFTER the update:
  L477  pt = demand_ema[iid] * pipeline_multiplier  (used when
        pipeline_multiplier > 0, as in all thesis runs)
  L481  S_dest = max(1, int(demand_ema[iid] * 3))   (only when
        pipeline_multiplier <= 0; not exercised here)
  ema_alpha is read ONLY at L436 (the update). Neither value is read
  anywhere else in the base or v2 simulator (verified by grep).
- Compensation: thesis_short_horizon_experiments.py, run_inventory()'s
  forecast_controlled_step (runner L221-243). Captures alpha = 0.05 once,
  sets pre-update demand_ema = (desired - alpha*actual)/(1-alpha), never
  mutates ema_alpha.
- Hold: notebook cell 106, ForecastDrivenCombinedSimulation
  ._apply_forecast_target (L537-586) + step (L588-599). On test days sets
  demand_ema = target/7 for every item (target keyed by block_start),
  then sets ema_alpha = 0.0. On warm-up days returns early (no change).

CONDITIONS UNDER WHICH EQUIVALENCE IS EXPECTED
----------------------------------------------
1. Identical initial state: same seed, same builder arguments, same
   scenario dict, same warm-start demand_ema (165.0) and ema_alpha (0.05).
2. Identical demand sequence: the same synthetic demand_fn for both sims.
3. Identical forecast targets: the same per-block forecast sums for both
   methods (compensation looks them up per day, hold looks them up per
   block_start; both resolve to the same block sum).
4. Injection on the same test days (TEST_START..TEST_END), applied BEFORE
   step()'s stage-4 EMA update in both methods.
5. No other code reads demand_ema before the update or mutates ema_alpha
   (verified: see Sources above).
6. Injection consumes no RNG in either method, so the simulators' RNG
   streams stay in sync (each sim has its own random.Random(seed)).
7. pipeline_multiplier > 0, so only the L477 read of demand_ema applies.
8. The test window extends to the end of the run, matching the thesis
   (cell 106 never restores ema_alpha after setting it to 0.0).

STATE / TIMING ASSUMPTIONS
-------------------------
- The hold method MUTATES ema_alpha to 0.0 (a global side effect);
  compensation does not. The trajectories are still equivalent because,
  after the first test day, hold's pre-update EMA is always set explicitly
  and alpha = 0 makes the native update a no-op. If any code read
  ema_alpha for another purpose, the methods could diverge (verified it
  does not: ema_alpha is read only at base L436).
- Compensation relies on the captured alpha matching the simulator's
  ema_alpha at run time. If the simulator's ema_alpha were changed
  without updating the captured value, equivalence would break (see
  test_wrong_coefficient_diverges).
- Compensation must be applied BEFORE the stage-4 update. Applying it
  after step() sets the wrong value (see test_wrong_stage_diverges).

NUMERICAL TOLERANCE
-------------------
Post-update EMA values are compared with math.isclose(rel_tol=1e-9,
abs_tol=1e-9). Justification: double-precision rounding on values of
order 10^2 is ~1e-13; 1e-9 is four orders above rounding but eight
orders below anything that could change a discrete decision. Discrete
decisions (shipments, served/unfilled, inventory/backlog/intransit
records) are compared with EXACT equality. The synthetic forecast
targets carry a 0.5 fraction (target_daily = ... + 0.5), so every
ship-target argument sits 0.5 away from the nearest integer and float
rounding (~1e-13) cannot flip a math.ceil decision.

FAILURE POLICY
--------------
If the implementations differ, the tests report the FIRST divergence
(day, item, values) and do not adjust anything to force a pass.

Run: python -m unittest tests.test_ema_equivalence -v  (from the stage-1 dir)
Only synthetic inputs are used. No thesis experiment is rerun.
"""

import contextlib
import hashlib
import io
import math
import os
import sys
import unittest
from pathlib import Path

# --- Locate the ACTUAL simulator (v2) and verify it is the audited file ---
# Default: the repository root (this file lives in <repo>/tests/).
# Override with THESIS_SIM_DIR to test a different copy.
SIM_DIR = Path(
    os.environ.get(
        "THESIS_SIM_DIR",
        str(Path(__file__).resolve().parent.parent),
    )
)
sys.path.insert(0, str(SIM_DIR))

# SHA-256 of the audited files (verified against the pushed repo state).
# If these do not match, the test refuses to run rather than silently
# testing a different implementation.
EXPECTED_SHA256 = {
    "Supplychaingeo_item50.py": "604b62788548697e1e2864c5e71c8182700e4dd7cd822b1615ab99394d1d2da7",
    "Supplychaingeo_item50_v2.py": "12fe0cdc7a962ebb190fc8ef010c17040727f36cdd750220fc167a7f0e18479f",
}

for _name, _expected in EXPECTED_SHA256.items():
    _actual = hashlib.sha256((SIM_DIR / _name).read_bytes()).hexdigest()
    if _actual != _expected:
        raise RuntimeError(
            f"F04 test: {_name} SHA-256 mismatch (expected {_expected}, got {_actual}). "
            "Refusing to test an unaudited implementation."
        )

import Supplychaingeo_item50_v2 as sim_v2  # noqa: E402

# --- Synthetic experiment design (identical for both methods) ---
SEED = 2025
HORIZON_DAYS = 31  # days 0..30
TEST_START = 10
TEST_END = 30  # test window 10..30 = exactly three 7-day blocks
FORECAST_HORIZON = 7
PIPELINE_MULTIPLIER = 7.0
MODEL_NAME = "Seasonal Naive"
# Runner's normal-scenario demand dict (thesis_short_horizon_experiments.py
# SCENARIOS["normal"]["demand"]); demand_fn is replaced by the synthetic
# lookup, so only the (s,S) / network construction sees this dict, and it
# is identical for both sims.
SCENARIO_NORMAL_DEMAND = {
    "phi_lo": 0.9990,
    "phi_hi": 0.9996,
    "shock_count_scale": 1.0,
    "shock_height_scale": 1.0,
    "seasonal_scale": 1.0,
    "burst_rate_scale": 1.0,
    "burst_height_scale": 1.0,
    "base_lambda_lo": 80,
    "base_lambda_hi": 250,
}


def _build_demand_lookup(item_ids):
    """Deterministic synthetic demand: (day, item) -> int units.

    Varies by weekday, by item, with one spike day (day 18) to exercise
    backlog dynamics. Same lookup is used for both methods.
    """
    lookup = {}
    for day in range(HORIZON_DAYS):
        for idx, iid in enumerate(item_ids):
            demand = 80 + (day % 7) * 6 + (idx % 5) * 12
            if day == 18:
                demand += 60
            lookup[(day, iid)] = int(demand)
    return lookup


def _build_block_sums(item_ids):
    """Per-block forecast sums: (block_start, item) -> 7-day forecast total.

    Target daily forecasts carry a 0.5 fraction so ship-target arguments
    sit 0.5 away from integer boundaries (see module docstring). Forecast
    targets deliberately differ from actual demand.
    """
    block_sums = {}
    for block_idx, block_start in enumerate(
        range(TEST_START, TEST_END + 1, FORECAST_HORIZON)
    ):
        for idx, iid in enumerate(item_ids):
            target_daily = 100.0 + (idx % 7) * 8.0 + block_idx * 15.0 + 0.5
            block_sums[(block_start, iid)] = 7.0 * target_daily
    return block_sums


def _build_sim(demand_lookup):
    """Build a fresh v2 sim (in-memory records) with synthetic demand_fn."""
    with contextlib.redirect_stdout(io.StringIO()):
        sim, net, items, _ = sim_v2.build_example_simulation_extended(
            seed=SEED,
            horizon_days=HORIZON_DAYS,
            pipeline_multiplier=PIPELINE_MULTIPLIER,
            streaming_out_dir=None,
            packing="greedy",
            scenario=dict(SCENARIO_NORMAL_DEMAND),
            disruption_p_onset=0.0,
            disruption_length_days=0,
        )
    item_ids = sorted(items.keys())
    sim.demand_fn = lambda day: {
        iid: demand_lookup[(day, iid)] for iid in item_ids
    }
    return sim, item_ids


def _run_with_wrapper(sim, item_ids, wrapper):
    """Run sim.run() with sim.step replaced by wrapper; capture EMA trace.

    The wrapper applies the injection, calls the original step, then the
    post-update demand_ema is recorded. Returns (ema_trace, sim) where
    ema_trace is a list over days of {item: post-update EMA}.
    """
    original_step = sim.step
    ema_trace = []

    def wrapped_step(day: int):
        wrapper(sim, day)
        original_step(day)
        ema_trace.append(dict(sim.demand_ema))

    sim.step = wrapped_step
    with contextlib.redirect_stdout(io.StringIO()):
        sim.run()
    return ema_trace, sim


# --- Injection wrappers (verbatim thesis logic; see module docstring) ---

def _compensation_wrapper_factory(block_sums, demand_lookup, alpha_override=None):
    """Runner's forecast_controlled_step, verbatim (L221-243).

    alpha is captured once from the simulator (0.05). alpha_override is
    used ONLY by the wrong-coefficient sensitivity test.
    """
    captured = {}

    def wrapper(sim, day: int):
        if "alpha" not in captured:
            captured["alpha"] = (
                sim.ema_alpha if alpha_override is None else alpha_override
            )
        alpha = captured["alpha"]
        if TEST_START <= day <= TEST_END:
            for iid in sim.items:
                block_start = TEST_START + ((day - TEST_START) // FORECAST_HORIZON) * FORECAST_HORIZON
                block_sum = block_sums[(block_start, iid)]
                desired_post_update_ema = block_sum / PIPELINE_MULTIPLIER
                actual_demand = demand_lookup[(day, iid)]
                # Compensate for the simulator's native EMA update so that
                # pipeline_multiplier * post-update EMA equals the 7-day forecast sum.
                sim.demand_ema[iid] = (
                    desired_post_update_ema - alpha * actual_demand
                ) / (1.0 - alpha)

    return wrapper


def _hold_wrapper_factory(block_sums):
    """Notebook cell 106's _apply_forecast_target + step, verbatim.

    On test days: demand_ema = target/7 per item (target keyed by
    block_start), then ema_alpha = 0.0. Warm-up days: no change.
    """
    def wrapper(sim, day: int):
        if day < TEST_START:
            return
        block_start = TEST_START + ((day - TEST_START) // FORECAST_HORIZON) * FORECAST_HORIZON
        for item in sim.items:
            key = (MODEL_NAME, str(item), int(block_start))
            target = block_sums[(block_start, item)]
            if target is None:
                raise KeyError(f"Missing forecast target: {key}")
            sim.demand_ema[item] = target / FORECAST_HORIZON
        # Keep the externally supplied forecast EMA from being overwritten
        # by today's realized demand.
        sim.ema_alpha = 0.0

    return wrapper


# --- Comparison helpers (first-divergence reporting) ---

def _first_ema_divergence(trace_a, trace_b, rel_tol=1e-9, abs_tol=1e-9):
    for day, (ema_a, ema_b) in enumerate(zip(trace_a, trace_b)):
        for iid in sorted(ema_a):
            a, b = ema_a[iid], ema_b[iid]
            if not math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol):
                return (day, iid, a, b, abs(a - b))
    return None


def _first_sequence_divergence(seq_a, seq_b):
    if len(seq_a) != len(seq_b):
        return ("length", len(seq_a), len(seq_b))
    for idx, (a, b) in enumerate(zip(seq_a, seq_b)):
        if a != b:
            return (idx, a, b)
    return None


class TestEmaEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Item IDs come from a probe sim so the test covers exactly the
        # items the simulator builds (no hardcoded item list).
        probe_sim, item_ids = _build_sim({})
        cls.item_ids = item_ids
        cls.demand_lookup = _build_demand_lookup(item_ids)
        cls.block_sums = _build_block_sums(item_ids)
        # Rebuild with the real demand lookup (probe used an empty lookup
        # only to discover item IDs; its sim is discarded).
        comp_sim, _ = _build_sim(cls.demand_lookup)
        hold_sim, _ = _build_sim(cls.demand_lookup)
        cls.comp_ema, cls.comp_sim = _run_with_wrapper(
            comp_sim, item_ids,
            _compensation_wrapper_factory(cls.block_sums, cls.demand_lookup),
        )
        cls.hold_ema, cls.hold_sim = _run_with_wrapper(
            hold_sim, item_ids, _hold_wrapper_factory(cls.block_sums)
        )

    def test_post_update_ema_equal(self):
        div = _first_ema_divergence(self.comp_ema, self.hold_ema)
        self.assertIsNone(
            div,
            f"EMA DIVERGENCE at day={div[0]}, item={div[1]}: "
            f"compensation={div[2]!r}, hold={div[3]!r}, |diff|={div[4]!r}"
            if div else "no divergence",
        )

    def test_daily_records_identical(self):
        div = _first_sequence_divergence(
            self.comp_sim.daily_records, self.hold_sim.daily_records
        )
        self.assertIsNone(
            div, f"DAILY RECORD DIVERGENCE at index {div[0]}: {div[1]!r} vs {div[2]!r}"
            if div else "no divergence",
        )

    def test_shipment_decisions_identical(self):
        div = _first_sequence_divergence(
            self.comp_sim.shipments_log, self.hold_sim.shipments_log
        )
        self.assertIsNone(
            div, f"SHIPMENT DIVERGENCE at index {div[0]}: {div[1]!r} vs {div[2]!r}"
            if div else "no divergence",
        )

    def test_inventory_backlog_intransit_identical(self):
        for name in ("inventory_history", "backlog_history", "intransit_history"):
            div = _first_sequence_divergence(
                getattr(self.comp_sim, name), getattr(self.hold_sim, name)
            )
            self.assertIsNone(
                div, f"{name.upper()} DIVERGENCE at index {div[0]}: {div[1]!r} vs {div[2]!r}"
                if div else "no divergence",
            )

    def test_warmup_days_identical(self):
        # Days 0..TEST_START-1 have no injection; both sims must agree
        # there too (guards against a build/initial-state mismatch).
        for day in range(TEST_START):
            comp_day = [r for r in self.comp_sim.daily_records if r["day"] == day]
            hold_day = [r for r in self.hold_sim.daily_records if r["day"] == day]
            self.assertEqual(comp_day, hold_day, f"warm-up day {day} differs")

    def test_wrong_stage_diverges(self):
        """Compensation applied AFTER step() must NOT match hold."""
        sim, _ = _build_sim(self.demand_lookup)
        block_sums, demand_lookup = self.block_sums, self.demand_lookup
        alpha = 0.05
        ema_trace = []
        original_step = sim.step

        def broken_step(day: int):
            original_step(day)
            if TEST_START <= day <= TEST_END:
                for iid in sim.items:
                    block_start = TEST_START + ((day - TEST_START) // FORECAST_HORIZON) * FORECAST_HORIZON
                    desired = block_sums[(block_start, iid)] / PIPELINE_MULTIPLIER
                    actual = demand_lookup[(day, iid)]
                    sim.demand_ema[iid] = (desired - alpha * actual) / (1.0 - alpha)
            ema_trace.append(dict(sim.demand_ema))

        sim.step = broken_step
        with contextlib.redirect_stdout(io.StringIO()):
            sim.run()
        div = _first_ema_divergence(ema_trace, self.hold_ema)
        self.assertIsNotNone(
            div,
            "wrong-stage variant unexpectedly matched hold; the test would "
            "not catch a stage-ordering bug",
        )

    def test_wrong_coefficient_diverges(self):
        """Compensation with a wrong alpha (0.10 vs simulator 0.05) must diverge."""
        sim, _ = _build_sim(self.demand_lookup)
        ema_trace, _ = _run_with_wrapper(
            sim,
            self.item_ids,
            _compensation_wrapper_factory(
                self.block_sums, self.demand_lookup, alpha_override=0.10
            ),
        )
        div = _first_ema_divergence(ema_trace, self.hold_ema)
        self.assertIsNotNone(
            div,
            "wrong-coefficient variant unexpectedly matched hold; the test "
            "would not catch a coefficient bug",
        )


if __name__ == "__main__":
    unittest.main()
