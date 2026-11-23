# Atlas Investment OS 3.0 — Current Verification Report

**As of:** 2026-11-23. **Scope:** standalone local prototype and an injected read-only IBKR bridge. **Production trading:** DISABLED.

## Reproducible result

```text
python -m unittest discover -s tests -q
----------------------------------------------------------------------
Ran 119 tests in 1.391s
OK

python -m atlas_pro
fixture_only: true
network_calls: 0
llm_calls: 0
broker_calls: 0
evidence_chain_valid: true
citation_retrieval_count: 1
p0_event_status: QUEUED
p0_agents: A012, A025
thanksgiving_exchange_closed: true
draft_policy_advisory_trade_blocked: true
live_orders_enabled: false
```

Installation test: `python -m pip install -e . --no-build-isolation --no-deps` succeeded and importing `atlas_pro` succeeded. Standard Python `compileall` passed.

## Statement coverage

`coverage run --source=atlas_pro -m unittest discover -s tests -q; coverage run -a -m atlas_pro; coverage report -m`

```text
src/atlas_pro/__main__.py       100%
src/atlas_pro/events.py          99%
src/atlas_pro/feeds.py           92%
src/atlas_pro/ibkr_bridge.py     81%
src/atlas_pro/ledger.py         98%
src/atlas_pro/licenses.py      100%
src/atlas_pro/models.py         91%
src/atlas_pro/release.py        87%
src/atlas_pro/retrieval.py      95%
src/atlas_pro/risk.py          100%
TOTAL                            95%
```

**Important:** branch coverage not measured. Most tests are synthetic, not real-provider integration tests. The reported 95% is statement coverage of *new small core*, not the entire IBKR Agent Harness or any autonomous financial research system.

## Specific regressions caught and fixed in this pass

1. **P0 policy intrusion routing:** prior draft used a department-prefix filter that could exclude a CIO security role. Now selects all registered P0 roles with a deterministic model, tested for `unauthorized_policy_change`.
2. **PIT timestamp canonicalization:** evidence timestamps are normalized to UTC before as-of filtering, preventing timezone string ordering errors.
3. **Private embedding leakage:** private documents and private retrieval queries reject arbitrary non-local embedding callbacks. Callers declaring `local_only=True` must still be isolated and operator-verified in actual deployment.
4. **Real-time vs replay:** IBKR bridge refuses paper/replay captures and missing reconciliation, and always returns `can_place_order=false`.
5. **Model certification expiry:** models without a current role-specific evaluation certificate cannot be auto-selected. The certificate itself requires authenticated control-plane verification in production.
6. **Budget race:** multiple concurrent reservations are serialized by `BEGIN IMMEDIATE`; a ten-thread synthetic test admitted only one request under a 5-cent daily cap.
7. **Data licensing:** FMP-like personal data can be used for permitted short-term personal analysis in the license policy but cannot become a permanent corpus or training/eval dataset by default.
8. **NYSE calendar:** 2026-11-26 holiday and 2026-11-27 shortened session were checked with installed `exchange_calendars 4.13.1`, not day-of-week guesswork.

## What remains unverified, and cannot honestly be marked closed

- No actual SEC, ALFRED, Bank of Canada, Tiingo, Alpaca or IBKR API credentials/entitlements were connected for this test.
- No live or paper brokerage order and no live read-only TWS session was run.
- No historical survivorship-free, point-in-time whole-universe equities dataset has been purchased/verified.
- No 50 simultaneous LLM agents were deployed. Registered roles and event dispatch are not hosted inference services.
- No paid cross-model financial benchmarks, model-specific latency/cost measurements, or real forecast calibration were performed.
- No live margin/maintenance margin method, options portfolio SPAN-style calculation or tax advisor sign-off.
- No local embedding model downloaded. Optional vector callback is not an end-to-end vector DB deployment.
- No externally verified signed approval identity management, vault, backup/disaster recovery, multiweek paper trading, incident response, or penetration test.
- GitHub repository `RyanYang053/IBKR-Agent-harness` was inspected read-only via connected GitHub. It was not modified or fully tested in this run.

## Release posture

**RESEARCH_ONLY / LOCAL_PROTOTYPE_PASS / PRODUCTION_RELEASE_BLOCKED**

Deploy no genuine trading, self-modifying investment mandates, or automatic strategy promotions. Proceed only in a feature branch with real provider entitlements, controlled financial evaluation datasets, live *read-only* broker shadow monitoring and strict user approvals.
