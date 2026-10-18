# Documentation guide

- [`experiment_protocol.md`](experiment_protocol.md) records the explicit horizon splits, model families, forecast measures, scenario definitions and current limits of the short-horizon runner.
- [`reproducibility_and_validation.md`](reproducibility_and_validation.md) records known source-data and implementation qualifications that affect result interpretation.
- [`methodology.md`](methodology.md) defines the evaluation window, metric definitions, ranking directions, agreement statistics, and the fill-rate identity (F02/F05).
- [`validation_and_limitations.md`](validation_and_limitations.md) is the repo-facing validation and known-limitations report: the status of audit findings F01–F05, what was verified, and what remains unverified.
- [`data_manifest.md`](data_manifest.md) lists what is included in this repository and what is missing (frozen source files, runner outputs).
- [`discrepancy_report.md`](discrepancy_report.md) records that F05 recomputation against locked/slide values is BLOCKED pending the frozen forecast files, with the prior trace labelled as not a recomputation.
- [`stage1_closeout_report.md`](stage1_closeout_report.md) is the Stage 1 closeout record for the validation work in `scripts/` and `tests/`.

The root [README](../README.md) is the project overview for recruiters, collaborators and general technical readers. These documents are intentionally more specific: they describe how to interpret the code and what remains to be independently checked.
