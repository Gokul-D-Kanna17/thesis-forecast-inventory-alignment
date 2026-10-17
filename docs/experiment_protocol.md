# Short-horizon experiment protocol

This file records the explicitly supplied split boundaries for the short-horizon runner. Day indices are zero-based and all end points are inclusive.

| Run length | Training window | Validation window | Test window | Forecast horizon |
|---:|---|---|---|---:|
| 2,000 days | 0–999 | 1,000–1,499 | 1,500–1,999 | 7 days |
| 3,000 days | 0–1,499 | 1,500–2,249 | 2,250–2,999 | 7 days |
| 5,000 days | 0–2,999 | 3,000–3,999 | 4,000–4,999 | 7 days |

The `TRAIN_END` and `VALIDATION_END` names in the code refer to the inclusive final day of each respective period. The implemented final test forecasting code uses pre-test observations through `VALIDATION_END`; review the actual model fitting code before describing any validation-based model-selection procedure in the thesis.

## Models and forecast metrics

- Seasonal Naïve
- Exponential Smoothing (ETS)
- LightGBM
- Mean Absolute Error (MAE), Root Mean Squared Error (RMSE), and Mean Absolute Scaled Error (MASE)

## Scenarios

- Normal
- Demand Disruption
- Supply Disruption
- Combined Disruption

Demand is frozen within each horizon/scenario in the runner so forecast models and inventory comparisons for that case are given the same realised demand series.

## Inventory evaluation and alignment

Inventory outcomes are evaluated separately for each forecasting model and inventory metric, rather than being collapsed into one composite score. The thesis question is whether forecast accuracy ranks and inventory-decision ranks align across conditions. The current runner produces forecast metrics and inventory rankings, but the explicit joined rank-alignment table remains to be implemented or otherwise verified. Do not state that alignment analysis is complete merely because the runner completes.

## Status

This protocol records the supplied split settings and current code structure; it is not evidence that any run completed successfully. Log the actual run command, date, dependency versions, completion status, and output locations when results are generated.
