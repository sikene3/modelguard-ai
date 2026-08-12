# ADR-006: Score, calibration, and threshold semantics

## Status
Accepted.

## Decision
The estimator/preprocessor Pipeline is cross-fitted and calibrated using training rows only.
Average precision versus prevalence is primary. A documented synthetic cost threshold is selected
on validation and locked, then the test is evaluated once per training invocation.
Brier/log-loss/reliability evidence is required.

The API score is calibrated only for the synthetic demo distribution. It is not a guaranteed
real-world fraud probability or economically optimal policy.

The locked held-out synthetic cost per event is the reference for the optional local label-backed
monitor policy. That heuristic describes only the labeled synthetic subset; it is not a statistical
significance test or proof of real-world/model-caused degradation.
