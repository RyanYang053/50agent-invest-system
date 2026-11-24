# Forecast probability calibration
1. Define a binary event, threshold, horizon, issue time and baseline before the outcome. Store model and strategy versions and cited inputs. A touch event and terminal event are distinct.
2. Resolve once at the predeclared measurement date using exact outcome evidence; keep unresolved and censored observations separate, never silently count them as failures or successes.
3. Brier score is mean squared probability error, mean((p-y)^2), for binary outcomes. Compare with the same observations under the frozen baseline. Display counts and calibration by fixed probability bins; sparse bins are uncertain.
4. Evaluate overlapping horizons and dependence. A naive independent standard error can overstate significance. Use a predeclared time-block design and do not select a winner from reused holdout data.
5. Record errors by horizon, strategy and version. A calibration adjustment is a proposal, not an automatic model or risk-policy change.
Acceptance: perfect and constant forecasts, contradictory outcomes, incomplete horizons, duplicated resolutions, wrong baseline and expired evidence must be tested.
Internal implementation: ForecastJournal and independent performance evidence modules. External research-data context: Kenneth French Data Library https://mba.tuck.dartmouth.edu/pages/faculty/Ken.French/data_library.html .
