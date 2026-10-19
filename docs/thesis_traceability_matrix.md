# How the code maps to the thesis

This file maps every important claim in my thesis to the code, data,
or docs in this repo, and says honestly where each one stands.
Where the thesis and the code differ, or where different parts of
the thesis give different accounts, I wrote it down instead of
papering over it. I did not change any reported thesis value to
make it match the code, or the other way around.

One thing to know up front: I could not recompute any thesis
number from the original experiment records, because those records
(the forecast files, inventory histories, runner outputs) are not
in this repo. I did run consistency checks calculated from values
printed in the thesis itself, mainly the appendix tables (see
§9.3, §9.5). Those checks compare the printed tables against
each other; they are not reproductions of the experiment.

**How to read the status column**

- **Verified** - I checked it against the stated evidence
  (code, printed thesis values, or supplied files). This means
  the check passed; it does not mean the experiment was
  reproduced.
- **Consistent, not rerun** - looks right, but the run or source
  data needed to confirm it isn't here.
- **Differs** - the code exists, but it gives a different result
  from the thesis.
- **Missing** - the thing doesn't exist.
- **Can't tell** - there isn't enough evidence to decide.
- **Differing thesis statements** - two parts of the thesis give
  different accounts; I record both and don't pick a side.

---

## 1. Research question and scope

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 1.1 | Main question (§1.6): to what extent do forecast-accuracy rankings correspond to inventory decision-quality rankings under normal and disrupted conditions? | README, `docs/methodology.md`, F03 script - no composite score, no universal winner | Verified |
| 1.2 | RQ1–RQ3 (§1.6, §4.8): accuracy differences; correspondence; change across horizons/conditions | F03 alignment script reports horizon/scenario breakdowns; runner + F05 produce accuracy metrics | Consistent, not rerun (no real-data run) |
| 1.3 | No composite score, no summed ranks, no single overall winner (§3.6.1, §4.4, §5.2) | F03 + runner build no composite; docs say so | Verified |
| 1.4 | No monetary cost metric (§1.8, §3.9, §5.2) | No cost function anywhere in the repo | Verified |
| 1.5 | Conclusion (§6.5): accuracy "does not consistently translate" into the same inventory ranking | Docs stick to the thesis position; no stronger claim | Verified |

## 2. Forecasting models

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 2.1 | Seasonal Naïve: seasonal period 7; the most recent 7 observations repeated for the 7-day forecast (§2.3.1, §3.4.1, Table E.3) | Runner `fit_and_forecast`; notebook cells 67/81 | Consistent, not rerun (runner never ran end-to-end on real data) |
| 2.2 | ETS: level-only, no trend, no seasonal component, estimated initialisation, optimised parameters, 7-day horizon (§2.3.2, §3.4.2, Table E.3) | Runner `ExponentialSmoothing(history, trend=None, seasonal=None).fit(optimized=True)`, refit per weekly origin | Consistent, not rerun |
| 2.3 | LightGBM features: lag_1/7/14/28, rolling_mean_7/28, rolling_std_28, day_of_week, week_of_year (§2.3.4, §3.4.3, Tables 3.3/E.4) | Runner `FEATURE_COLS` - same list | Verified (read the code) |
| 2.4 | LightGBM settings: 300 estimators, lr 0.05, 31 leaves, max depth unrestricted, subsample 0.8, colsample 0.8, seed 2025 (Tables 3.3/E.4) | Runner `LGB_PARAMS` - same values | Verified (read the code) |
| 2.5 | LightGBM subsampling: thesis lists subsample 0.8 / colsample 0.8 with no further detail | Runner passes `subsample=0.8` with `subsample_freq` unset (default 0), which means **bagging is off and subsample does nothing** (per LightGBM docs); `colsample_bytree=0.8` is active. The notebook LightGBM sets neither (feature fraction 1.0). Written up in `docs/experiment_protocol.md`; I didn't change the code, because that would change the experiment | Consistent, not rerun (protocol difference documented; LightGBM not executed here) |
| 2.6 | 7,300-day Supply LightGBM uses expanding-history refit at each origin + zero clipping; shorter horizons use train-once, no clipping (§3.4.3, §5.3, App. E.7) | Notebook cell 89 (refit + `max(0,pred)`); runner train-once, no cap. The thesis states this difference and so do the repo docs | Verified (code + thesis agree the difference exists) |
| 2.7 | Recursive 7-day forecasts "using only information available at the relevant forecast origin" (§2.3.4) | Runner recurses within 7-day blocks; no leakage found (features shifted, ETS refits on observed history) | Consistent, not rerun |

## 3. Scenarios and disruption mechanisms

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 3.1 | Four conditions: Normal, Demand, Supply, Combined (Tables 3.2/E.2) | Runner `SCENARIOS`; notebook cells per scenario | Verified (read the code) |
| 3.2 | Demand Disruption: shock-count scale 2.0 AND shock-height scale 2.0 (§3.3, Table E.2) | Runner demand-disruption config - both scales 2.0 | Verified (read the code) |
| 3.3 | Supply Disruption: source-outage onset probability 0.001, duration 30 days (§3.3, Table E.2) | Runner supply config `p_onset 0.001`, length 30 | Verified (read the code) |
| 3.4 | Combined = demand + supply modifications at the same time (§3.3) | Runner combined scenario applies both | Verified (read the code) |
| 3.5 | Paired demand: Normal ≡ Supply demand; Demand ≡ Combined demand (§3.3, §3.7, Table E.2) | Checked in notebook cells 90/106 (PASS); runner uses frozen demand per scenario | Consistent, not rerun (paired files not in repo) |
| 3.6 | 990 unavailable source-days in Supply/Combined | Notebook cell 106 output reports `unavailable_source_days 990`; can't recompute from the repo | Can't tell (no source records in repo) |

## 4. Simulator and environment

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 4.1 | ISOMORPH 50-SKU setup; destination New York; 3 source nodes; multi-echelon network (§3.2, Tables 3.1/E.1) | `Supplychaingeo_item50.py` + `Supplychaingeo_item50_v2.py` in repo root (13-node network, destination New York, 50 items) | Consistent, not rerun (simulator never ran end-to-end here) |
| 4.2 | ISOMORPH version/commit pinned | **Not done.** The simulator files are plain copies with no version, commit hash, submodule, or provenance record. The thesis cites `github.com/tuhinsahai/ISOMORPH` and Zhang et al. (2026) without a version. Don't assume these files match any particular ISOMORPH commit. | Missing |
| 4.3 | EMA update `EMA_t = 0.05·D_t + 0.95·EMA_{t-1}`; pipeline target `PT = 7 × EMA` (§3.5, Table E.5) | Base simulator: initial EMA 165.0, `ema_alpha = 0.05`, stage-4 update, stage-5 shipping reads post-update EMA | Verified (read the code) |
| 4.4 | Forecast integration: "EMA state adjusted so the resulting pipeline target corresponds to the model's seven-day forecast total" (§3.5, Table E.5) - the thesis only describes the compensation method (`EMA*_{t-1} = (EMA*_t − 0.05·D_t)/0.95`) | Runner + notebook Normal/Demand use compensation. Notebook Supply (cell 91) and Combined (cell 106) use the **hold** method (set `demand_ema = target/7`, `ema_alpha = 0.0`, never restored). The thesis does not mention the hold variant. My F04 test (`tests/test_ema_equivalence.py`) shows compensation ≡ hold for the tested synthetic conditions on the real simulator (7/7 pass, exact shipment/inventory equality). | Differs (procedure differs by scenario in code; equivalence shown only for tested synthetic conditions; 7,300-day runs not rerun) |
| 4.5 | Packing rule: Greedy packing (Tables 3.1/E.1) | Simulator implements `allocate_units_along_path_greedy`, `packing="greedy"` | Verified (read the code) |
| 4.6 | Base demand intensity 80–250 (Tables 3.1/E.1); realised demand is stochastic, not fixed at 80–250 | Runner `build_demand_fn` base λ 80–250; thesis caveat repeated in docs | Consistent, not rerun |
| 4.7 | Pipeline multiplier 7 ≠ 7-day forecast horizon (the thesis stresses the distinction, §3.2) | Docs + runner docstring say so | Verified |

## 5. Horizons, splits, and evaluation windows

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 5.1 | Four horizons: 2,000 / 3,000 / 5,000 / 7,300 days, each generated independently from day 0 (§1.8, §3.7, §4.1, Table E.6) | Runner `HORIZONS` (separate runs per horizon); docs say horizons are sensitivity settings, not replications | Consistent, not rerun |
| 5.2 | Train/validation/test split boundaries | **The thesis does not state the split days.** The notebook defines the 7,300-day splits (train 0–5099, validation 5100–6199, test 6200–7299). The runner defines the shorter-horizon splits (2000: test 1500–1999; 3000: test 2250–2999; 5000: test 4000–4999). Those boundaries come from the implementation, not the thesis - don't cite the thesis for them. | Can't tell (thesis-silent; implementation-defined) |
| 5.3 | Primary comparison window: test window days 6200–7299 (1,100 days) for 7,300-day results | F01 script + corrected notebook cell 106 filter to 6200–7299; runner filters to configured test days | Verified (read the code; real-data run blocked) |
| 5.4 | 7,300-day Combined inventory in the thesis uses the test window | **No.** Thesis Appendix B.4 Combined values (fill 0.1385, unfilled 87,816,644, shipments 335,681,841, …) match the notebook cell 106 **full-horizon** output. The thesis puts them next to test-window values for the other scenarios without noting the window difference (see §11.5). The repo documents this and provides the F01 test-window recomputation for when the records are available. | Differs (thesis reports window-mixed values; repo does not reproduce them) |
| 5.5 | Shorter horizons generated in a dashboard-based environment; 7,300-day in the Python notebook (§3.7, App. E.7) | The repo's runner is a **reimplementation** of the shorter-horizon protocol, NOT the original dashboard code that generated the thesis's 2,000/3,000/5,000-day results. Don't claim the runner generated the thesis's shorter-horizon results. | Consistent, not rerun (provenance gap documented) |

## 6. Forecast metrics and aggregation

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 6.1 | MAE = mean \|y − ŷ\|; RMSE = sqrt(mean (y − ŷ)²) (§2.2.1–2.2.2) | Runner `forecast_metrics`; F05 script; unit tests with hand-computed values | Verified (code + tests) |
| 6.2 | MASE = MAE / Scale; Scale = mean \|y_t − y_{t−7}\| over training history (§2.2.3) | F05 script (training 7-lag denominator, mean over items); runner (pre-test history through `VALIDATION_END`) | Consistent, not rerun (no real forecast files in repo) |
| 6.3 | MASE denominator range: "training history" (the thesis doesn't pin the exact day range) | The repo documents the implemented convention (days 0..`VALIDATION_END`, i.e. 0–6199 for 7,300 days, matching notebook cell 112). The thesis's phrase is ambiguous between train-only (0–5099) and pre-test (0–6199); the repo follows the notebook. | Can't tell (thesis ambiguous; repo follows notebook) |
| 6.4 | Zero/invalid MASE denominator handling | Runner records NaN + explicit warning; F05 errors explicitly; F03 rejects non-finite values. The thesis doesn't discuss the case. | Verified (code + tests; thesis-silent) |
| 6.5 | Primary aggregation: per-item MAE/RMSE/MASE, then **mean** across items (§4.3, App. D note 1) | F05 (mean primary); F03 (mean primary); runner summary reports mean_ and median_ | Verified (read the code) |
| 6.6 | Median-of-item ranks as sensitivity: ordering changes in 18/48 horizon×scenario×metric cells; winner changes in 12/48; 7,300-day rankings agree (§4.3, App. D) | F03 `sensitivity_median_forecast_ranks` does the same comparison. The thesis's 18/12 counts aren't recomputed (needs item-level files). | Consistent, not rerun |
| 6.7 | MAE/RMSE/MASE give identical model orderings within every horizon×scenario (mean-based) (§4.2, §4.5, §5.1) | F03 treats the three forecast metrics as separate combos with identical orderings; checked against Appendix A values (see §9.2) | Verified (thesis-appendix check) |
| 6.8 | Appendix A.4 (7,300-day) Supply forecast values equal Normal values exactly (SN/ETS all six numbers; LGBM all but MAE_mean) | **Differs from the notebook locked table**, which has distinct Supply values (SN RMSE 22.368811 vs Normal 22.0150; SN MASE 0.999848 vs 1.0363; LGBM RMSE 18.028672 vs 19.4331; LGBM MASE 0.802176 vs 0.8974). The two sources disagree, and the available records do not establish which is correct; the locked Supply values are themselves untraceable (cell 89 output truncated). See §11.4. | Can't tell (thesis appendix vs notebook locked table disagree) |

## 7. Inventory metrics and aggregation

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 7.1 | Ten recorded measures: fill rate, total unfilled demand, avg/max destination inventory, avg/max total network inventory, avg/final/max destination backlog, total shipment units (§3.6, App. B intro) | Runner + F01 record all ten values | Verified (read the code) |
| 7.2 | Six ranked measures: fill rate, total unfilled demand, avg destination inventory, avg destination backlog, max destination backlog, avg total network inventory (§4.4, App. B intro, App. B.2) | F03 `PRIMARY_INVENTORY_METRICS` = exactly these six; runner `INVENTORY_RANK_DIRECTIONS` = exactly these six (fixed in this commit; the runner used to rank all ten) | Verified |
| 7.3 | Four descriptive measures NOT ranked: max destination inventory, max total network inventory, final destination backlog, total shipment units (§4.4, App. B intro, App. B.4 note) | Runner records values, does not rank them (fixed in this commit); F03 excludes them | Verified |
| 7.4 | Directions: fill rate higher-is-better; other five ranked lower-is-better (§4.4, App. B.2, Table 3.5) | F03 + runner direction maps match; tests check each direction | Verified |
| 7.5 | Shipments "interpreted descriptively", no automatic direction (Table 3.5, App. B.4 note) | Runner/F03 don't rank shipments; docs say why | Verified |
| 7.6 | Aggregation: daily aggregates (sum across items/nodes per day, then mean/max across test days) | Runner `compute_inventory_metrics` (v2) + F01 script use daily aggregates; hand-computed fixture tests | Verified (code + tests) |
| 7.7 | Fill rate + total unfilled demand give identical rank orderings by construction (same demand + window) | F03 documents the redundancy; primary keeps both, sensitivity excludes one; §5.1 of the thesis reports both without noting the redundancy | Verified (thesis reports both; repo documents the redundancy) |
| 7.8 | Appendix B.3 (5,000-day) inventory values identical to B.2 (3,000-day) | B.3's values match B.2's. The thesis presents B.3 as 5,000-day results and does not state that they duplicate B.2. The repo documents the duplication as a limitation; see §11.3 and `docs/reproducibility_and_validation.md` §1 for method, source, and uncertainty. | Verified (thesis-appendix check) |

## 8. Ranking and alignment procedure

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 8.1 | ΔR = R_inventory − R_forecast per model; \|ΔR\|; mean \|ΔR\| over N model-level comparisons (§3.6.1) | F03 computes exactly these; unit tests with hand-checked values | Verified (code + tests) |
| 8.2 | Exact agreement definition | **The thesis gives two different definitions.** §4.5 / App. C.3 define it as model-level (Δ = 0 per model). App. C.1 defines it as equality of the complete three-model ordering. The repo's F03 reports BOTH, labelled separately, and never mixes them up. See §11.1. | Differing thesis statements (repo implements both, labelled) |
| 8.3 | Framework size: 288 vs 456 combinations | **The thesis gives two different numbers.** Abstract says 456; App. C.1 says 288. Table 4.2's values are consistent with the 456 framework (see §9.3). The repo's F03 implements the 288 framework (per §4.4 / App. B / App. C.1's stated procedure). See §11.2. | Differing thesis statements (repo implements 288, documents 456) |
| 8.4 | Spearman rank correlation as supplementary DESCRIPTIVE measure only; not primary (§3.6.1, §3.9, §5.3) | F03 reports Spearman + Kendall descriptively only, no p-values/CIs/SEs; docs state the n=3 coarseness | Verified |
| 8.5 | Tie handling | The thesis doesn't state a tie method. The repo's F03 uses **average** ties (a documented choice). The thesis's Table 4.2 7,300-day MAD matches only with **min** ties in the 456 framework (see §9.3) - consistent with the thesis's alignment having used min ties (same as the notebook locked table's `rank(method="min")`). The repo deliberately keeps average (the standard choice) and documents the difference; it doesn't switch to min just to match the printed result. | Can't tell (thesis-silent; repo choice documented; difference quantified) |
| 8.6 | 2,000-day max-destination-backlog three-way ties (Normal 660,245; Supply 684,389) | Thesis App. B.1/B.5 confirm the ties; F03 handles ties via average method; §3.6.1 anticipates tied ranks | Verified (thesis-appendix check) |

## 9. Reported results

### 9.1 Table 4.1 - Forecast-method rankings by horizon/scenario

Checked against Appendix A values: every ordering in Table 4.1
matches the Appendix A mean values (e.g. 2,000-day Normal
ETS 16.1064 < SN 18.0718 < LGBM 19.3767; 3,000-day Normal
LGBM 14.2989 < ETS 14.3372 < SN 16.3168; 5,000/7,300-day
LGBM → ETS → SN everywhere). **Thesis-internally consistent.**
Repo status: Consistent, not rerun (no forecast files in repo;
runner implements the same models).

### 9.2 Appendix A values vs notebook locked table (7,300-day)

- Normal: Appendix A.4 = locked table (MAE/RMSE/MASE match to
  displayed precision). **Consistent.**
- Demand: Appendix A.4 mean-of-item values (MAE 20.7721,
  RMSE 26.2474, MASE 1.0781 for SN) vs locked table (MAE
  20.772073, RMSE 26.689412 pooled, MASE 0.999708 slide).
  Locked MAE matches; locked RMSE/MASE are the pooled/slide
  values, NOT the Appendix A.4 mean-of-item values. **The
  appendix and the locked table use different aggregations
  for Demand** (see §11.4).
- Supply: Appendix A.4 = Normal exactly; locked table has
  distinct Supply values. **The two sources disagree**
  (see §11.4).
- Combined: Appendix A.4 = Demand mean-of-item values; locked
  table = Demand pooled/slide values. Same aggregation split
  as Demand.

### 9.3 Table 4.2 / Appendix C.2 - Alignment across horizons

Thesis reports (MAD / exact): 2,000d 0.933 / 32.5%;
3,000d 0.967 / 25.8%; 5,000d 1.050 / 25.0%;
7,300d 0.990 / 32.3%.

Method: ranks recomputed from the printed Appendix B.4
values, plus unrounded Normal fill rates from the locked
table (the only unrounded values available). Source: thesis
Appendix B.4, Table 4.2, locked table. This is a
printed-value consistency check, not a reproduction from
experimental records.

I recomputed the 7,300-day statistics from Appendix B.4
values (+ unrounded Normal fill rates from the locked table):

| Computation | MAD | Exact |
| --- | --- | --- |
| Thesis Table 4.2 (7,300d) | 0.990 | 32.3% |
| 456 framework, min ties | **0.9896 (285/288)** | **32.29% (93/288)** |
| 456 framework, average ties | 0.9792 (282/288) | 32.29% (93/288) |
| 288 framework (either tie method) | 0.9722 (210/216) | 34.72% (75/216) |
| 288 framework, B.8 printed ranks | 0.9167 | 36.11% |

What this tells me: (a) Table 4.2's 7,300-day values match
the **456 framework with min ties** to the printed
precision, and do not match the 288 framework the thesis's
§4.4/App. B describe; (b) the exact-agreement value doesn't
depend on the tie method, the MAD does; (c) the repo's F03
(288 + average ties) gives 0.9722/34.72% for 7,300 days
from the same B.4 values - it does **not** reproduce
Table 4.2, by design (it implements the thesis's stated
6-metric procedure, not the 456 framework the Table 4.2
numbers are consistent with). For 2,000/3,000/5,000 days,
Table 4.2's percentages fit the 456 framework's
whole-number counts (117/360, 93/360, 90/360) but not the
288 framework's (70.2/216 at 2,000 days isn't a whole
number) - consistent with 456 provenance for all horizons,
though I only fully recomputed 7,300 days.

Uncertainty: the thesis does not state which framework
Table 4.2 uses. The 456 attribution is an inference from
the numbers matching under 456 + min ties and not matching
under 288, not a stated fact.

### 9.4 Table 4.3 - Fill-rate ranges at 7,300 days

Values match the locked table / B.4 (Normal 0.997953–0.999209;
Demand 0.038193–0.041974; Supply 0.998494–0.998654;
Combined 0.137621–0.138485). **But** the Combined range is
full-horizon while the others are test-window (see §5.4) -
the thesis presents them side by side without noting the
window difference.

### 9.5 Appendix B.8 ranking matrices vs Appendix B.4 values (7,300 days)

Method: for each of the 24 scenario-by-metric cells, rank
the three models by the printed B.4 values and compare
against the B.8 printed ranks. No ties affect the eight
differing cells below. Source: thesis Appendices B.4 and
B.8. This is a printed-value consistency check, not a
reproduction from experimental records.

B.8 differs from B.4's own values in **9 of 24 cells**:
Normal fill (B.4 rounds SN/LGBM both to 0.9992; unrounded
locked values give SN→LGBM→ETS, matching B.8 - this cell is
consistent with B.4 rounding, not a B.8 difference),
Demand network (B.8 ETS→LGBM→SN; values give
SN→ETS→LGBM), Supply avg destination inventory (B.8
LGBM→ETS→SN; values give SN→LGBM→ETS), Supply avg
backlog (B.8 ETS→LGBM→SN; values give ETS→SN→LGBM),
Supply max backlog (B.8 ETS→LGBM→SN; values give
SN→ETS→LGBM), Supply network (B.8 ETS→LGBM→SN; values
give LGBM→ETS→SN), Combined avg backlog (B.8 SN→ETS→LGBM;
values give LGBM→SN→ETS), Combined max backlog (B.8
SN→ETS→LGBM; values give SN→LGBM→ETS), Combined network
(B.8 ETS→LGBM→SN; values give LGBM→ETS→SN). **Eight cells
differ** (excluding the Normal-fill rounding case). B.8's
network-inventory row differs from the B.4-based ordering
for all three non-Normal scenarios. Any alignment
statistic computed from B.8 as printed would differ from
one computed from B.4 values (288-framework: B.8-based
MAD 0.9167/exact 36.11% vs B.4-based 0.9722/34.72%).
B.5 (2,000d) and B.6 (3,000d) are consistent with B.1/B.2
where display precision allows checking; B.7 (5,000d)
is identical to B.6, as expected from the duplicated
values.

Uncertainty: B.8 may have been computed from unrounded
values that are not printed in the thesis. The printed
tables alone show an inconsistency between the two
appendices; they do not establish which table is in error.

### 9.6 Appendix D - Mean vs median

Thesis: ordering changes in 18/48 cells, winner changes in
12/48; 7,300-day rankings agree. Repo F03 implements the
same median sensitivity. Counts not recomputed (needs
item-level files). Consistent, not rerun.

### 9.7 Figures 2.1, 3.1, 4.1–4.4

The figures are images, so I couldn't pull their numbers out
of the text - I didn't check them. The thesis says Figure 4.1
"carries the numerical values". Status: Can't tell.

### 9.8 Appendix E - Configuration tables

E.1–E.7 match the thesis body and the repo's documented
configuration (ISOMORPH, 50 SKUs, New York, seed 2025,
pipeline 7, greedy packing, shock scales, outage
parameters, LightGBM params, EMA 0.05, dashboard-vs-notebook
provenance, Supply-LGBM qualification). Verified
(documentation-level).

### 9.9 Appendix C.1 - Table C.1

I couldn't read Table C.1's rows from the text available to
me. Its surrounding paragraph states the 288 framework and
defines exact agreement as complete-ordering equality -
giving a different definition from §4.5/C.3 (see §11.1).
Status: Can't tell (content not readable; surrounding text
gives a different definition from §4.5).

## 10. Limitations and boundary conditions

| # | What the thesis says | Where it lives in the repo | Status |
| --- | --- | --- | --- |
| 10.1 | Synthetic environment; not a real company (§3.9, §5.3, §6.4) | Docs say so | Verified |
| 10.2 | Only three methods (§3.9, §5.3) | Docs say so | Verified |
| 10.3 | Fixed 7-day horizon (§3.9, §5.3) | Docs say so | Verified |
| 10.4 | Non-monetary, rank-based; rank differences don't keep the magnitudes (§3.9, §5.3) | Docs say so; F03 reports ranks only | Verified |
| 10.5 | Horizons are sensitivity settings, not independent replications (§3.7, §3.9, §4.7, Table E.6 note) | Docs say so; F03 does no pooled inferential statistics | Verified |
| 10.6 | 7,300-day Supply LGBM refit+clip limits cross-horizon interpretation (§5.3, §6.4, App. E.7) | Docs say so | Verified |
| 10.7 | Rank statistics (incl. Spearman) are descriptive, not strong evidence (§3.9, §5.3) | F03 reports correlations descriptively only | Verified |

## 11. Differing statements inside the thesis (recorded, not resolved)

These are places where different parts of the thesis give
different accounts. I record them accurately and don't
pretend they're resolved.

1. **Exact-agreement definition.** §4.5 and App. C.3 define
   exact agreement as model-level (Δ = 0 per model). App. C.1
   defines it as equality of the complete three-model
   ordering. The thesis gives two different definitions.
   The repo's F03 reports both, labelled separately.
2. **Framework size.** Abstract: 456 combinations. App. C.1:
   288 combinations. §4.4 / App. B: 6 ranked metrics (which
   implies 288). Table 4.2's values are consistent with 456
   (see §9.3). The repo implements 288 (the thesis's stated
   procedure) and documents that Table 4.2's numbers match
   the 456 framework.
3. **Table 3.5 vs §4.4 on directions.** Table 3.5 assigns
   directions to all ten metrics ("lower is better, subject
   to service" for max inventories). §4.4 / App. B say the
   four descriptive measures aren't ranked "because a unique
   optimisation direction is not specified for them". The
   repo follows §4.4/App. B (rank six).
4. **Appendix A.4 vs locked table on Supply.** A.4 sets
   Supply = Normal exactly; the locked table has distinct
   Supply values (see §6.8). The locked Supply values are
   themselves untraceable (cell 89 truncated). The available
   records do not establish which source is correct.
5. **Appendix B.3 duplication.** B.3 (5,000-day) inventory
   values are identical to B.2 (3,000-day). The thesis does
   not state this. The repo documents it.
6. **Appendix B.4 Combined window.** B.4 Combined values are
   full-horizon; other scenarios are test-window. The thesis
   presents them side by side (Tables 4.3, B.4, B.8) without
   noting the window difference.
7. **Appendix B.8 vs B.4 differences (§9.5).** B.8's printed
   rankings differ from the B.4-based orderings in 8 of 24
   cells at 7,300 days (a 9th, Normal fill, is consistent
   with B.4 rounding - the unrounded locked values match
   B.8). The printed tables alone do not establish which
   table is in error.
8. **EMA procedure (§4.4).** The thesis describes only the
   compensation injection; the code also uses the hold
   injection for Supply/Combined. Equivalence shown for
   tested synthetic conditions only.
9. **Section numbering.** The thesis's Table of Contents
   lists §3.3 as "Experimental Configuration" and §3.7 as
   "Experimental Conditions", but the body has §3.3 "Demand
   Generation and Operating Conditions" and §3.7
   "Experimental Conditions and Horizon Robustness".
   Cosmetic; doesn't affect results.
10. **Table C.1.** Rows not readable from the text available
    to me; surrounding text gives a different exact-
    agreement definition from §4.5.

## 12. Missing inputs (nothing below was made up)

- Original forecast files, inventory histories, runner
  outputs, and frozen demand files (all under
  `D:\ISOMORPH\thesis_frozen\` on my machine) - needed for
  F01/F05/F03 real-data runs and for reproducing Tables
  4.1/4.2/4.3 and Appendices A–D.
- ISOMORPH version/commit for the simulator files.
- Figure values (the figures are images; I couldn't extract
  their numbers).
- Table C.1 rows (not readable from the text available to me).
- Exact split boundaries in the thesis (thesis-silent;
  implementation-defined).
