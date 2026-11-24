# Price-behavior and controlled skill evolution (candidate)

Reference: PA_Agent, https://github.com/rosemarycox5334-debug/PA_Agent/tree/2b3c74e9e5619ed390097b1f6f53aebe88ce097c (AGPL-3.0 per README).
Atlas uses an independently implemented daily-bar diagnostic and review routing.
No PA_Agent source, prompts, thresholds, chart assets, or historical records
are bundled. A future direct-code integration must preserve the upstream
copyright, full license, corresponding source and applicable network-use
obligations; do not relicense the entire repository implicitly.

Design adaptations: two-phase market diagnosis and review routing; closed-bar
point-in-time checks; deterministic numeric feature calculations; replayable
evidence hashes and decision nodes; previous-watch invalidation and expiration.
A065 accepts an optional price_behavior request with security_id and
record_ids (61–200 daily OHLCV evidence records) plus optional prior watch.
It never fetches data automatically, asserts a fill, estimates probability,
or constructs an order. A same-bar crossing of both levels is explicitly
ambiguous. Calendar gaps, corporate actions, provider rights, real-data
calibration and cross-regime performance remain independent requirements.

Skill evolution adds bounded quality-check hypotheses from repeated role-local
task episodes; immutable candidate packs, preregistered holdout IDs, paired
evaluation, two independent signatures and owner-approved release staging.
Rollback removes staging, not a deployed binary. The numeric paired benchmark
compares prompt variants with identical cases and explicit split budget, but
does not certify full role competence. Actual qualified independent answers,
reviewers and new runtime certificates remain necessary for release.

QuantLib is optional and independently crosschecked for European vanilla
option valuations; the actual library is installed in its dedicated CI job.
The daily maintenance command supports BLS/ALFRED/BoC and NIST refresh plus
role reflection; run it using an operator-owned scheduler, not broker access.
It records one tick per UTC day and blocks ambiguous retry. This does not
install an always-on process or assert real provider connectivity.

Outstanding: live data and rights-cleared reference files, validated
exchange-session and corporate-action aware OHLCV ingestion, historical
walk-forward price-action evaluation, Qlib/RD-Agent/LEAN actual external
execution, independent professional role certification, automatic live
method activation (deliberately forbidden), and operator scheduler deployment.
