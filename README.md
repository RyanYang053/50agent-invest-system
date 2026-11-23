# Atlas Investment OS 3.0 — Professional Research Upgrade

> **Research-only / no live trading / no owner policy changes by AI.**
>
> A reproducible local engineering reference implementation built on top of the previous 50-Agent pack. This **does not** install or modify the existing `IBKR-Agent-harness` repository.

## Verified here

- 50 logical roles and 21 registered event routes from the previous pack.
- Added a real local, testable read-only core (`src/atlas_pro/`) with: evidence ledger, source/available-at checks, source license gate, FTS5 retrieval, vector callback interface, event queue + exchange calendar, model certification and atomic budget admission, IBKR read-only snapshot bridge, source-adapter contracts, risk refusal, owner-signature-based release proposal gate.
- 119 tests passed offline; combined new module + CLI smoke statement coverage approximately 95% using this container's Python and `exchange_calendars`.
- The `python -m atlas_pro` demo is synthetic with no API keys, no account requests, no paid models and no orders.

## Quick start

```bash
python -m pip install -e ".[market_calendar]"
python -m atlas_pro
python -m unittest discover -s tests -v
```

The `src/atlas_policy_router.py` reference router and previous 60 tests are retained unchanged. New code is under `src/atlas_pro/` and new tests under `tests/test_production_core.py`.

## Documents

- `docs/Professional Engineering Readiness.md`: new implemented features, provider comparison, license permissions, exact verification boundary, G0–G7 production acceptance gates.
- `docs/Architecture and Operations.md`: existing architecture and 50-role design.
- `docs/Verification Report.md`: previous 60-test report (kept for provenance; **superseded** by new verification report).
- `config/providers/personal data source catalog.json`: source-level acquisition, licensing and point-in-time caveats.
- `config/50 agent manifest.json` and `config/event rules.json`: roles and events.
- `src/atlas_pro/__main__.py`: offline integration smoke.

## Critical caveats

- Local reference implementation, **not live-price**, **not live-broker**, **not secure third-party model certification**, **not an audited margin engine**.
- The IBKR bridge is read-only and accepts only external broker snapshots already captured by the existing harness; no actual broker login was executed.
- Qwen3-Embedding and Qdrant are recommended components, **not installed by this package**. Without a local embedding callback, search is FTS5 lexical, not proven semantic RAG.
- Financial data supplier license terms override code capabilities. FMP's November 2026 AI terms notably ban using FMP data to train or evaluate models; the default license gate denies such usage.
- Tests use synthetic data. To close production gaps, run real paid-model evaluations and shadow/paper monitoring under explicitly authorized personal account connections, without placing orders.
