# Documentation guide

- [`thesis_traceability_matrix.md`](thesis_traceability_matrix.md) maps every material thesis claim (models, scenarios, simulator, metrics, rankings, reported tables) to the corresponding repository artifact, with an explicit status - including places where different parts of the thesis give different accounts (456 vs 288 framework, B.8 vs B.4 orderings, A.4 Supply values vs the locked table, the 5,000-day duplication the thesis does not state, the Combined full-horizon window).
- [`experiment_protocol.md`](experiment_protocol.md) records the explicit horizon splits, model families, forecast measures, scenario definitions and current limits of the short-horizon runner.
- [`reproducibility_and_validation.md`](reproducibility_and_validation.md) records known source-data and implementation qualifications that affect result interpretation.
- [`methodology.md`](methodology.md) defines the evaluation window, metric definitions, ranking directions, agreement statistics, and the fill-rate identity (F02/F05).
- [`validation_and_limitations.md`](validation_and_limitations.md) is the validation and known-limitations report: the status of checks F01–F05, what was verified, and what remains unverified.
- [`data_manifest.md`](data_manifest.md) lists what is included in this repository and what is missing (frozen source files, runner outputs).
- [`discrepancy_report.md`](discrepancy_report.md) records that F05 recomputation against locked/slide values is BLOCKED pending the frozen forecast files, with the prior trace labelled as not a recomputation.

The root [README](../README.md) is the project overview for recruiters, collaborators and general technical readers. These documents are intentionally more specific: they describe how to interpret the code and what remains to be independently checked.
