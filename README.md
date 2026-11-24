# Atlas Investment OS — research runtime 0.4.0

A local-first investment research system with 50 logical specialist roles and 21 event routes. **Research only; no live order submission or AI modification of owner risk policy.** The existing IBKR-Agent-harness is not modified.

## Quick start (from repository checkout)

```bash
python -m pip install -e '.[market_calendar,test]'
python -m pytest -q
python -m atlas_pro
```

The demo and tests are offline and use synthetic data or provider-shaped fixtures. They are not proof of profitability, live data coverage or model accuracy.

## Research capabilities

- Point-in-time SEC annual financial normalization using accession and filing acceptance timestamps, evidence ledger, source licensing, FTS5 retrieval, optional local pinned embedding integration.
- User-supplied stock universe (1–100 securities), fundamental and valuation screening with missing-data refusal; optional Alpaca IEX research quotes and SEC outstanding share extraction.
- FCFF DCF, reverse DCF, scenario returns, conditional Kelly, conservative decision grid; no trade permission.
- Model execution adapters for OpenAI, DeepSeek and Anthropic, with explicit opt-in, certification, scope and token/budget limits, citation membership checks, and role-scoped registered tool interface.
- Durable event leases, scheduled tick/worker reference implementation, forecast journal, Brier calibration, locked evaluation and PIT return-interval replay.

## Stock screening

```bash
atlas-screen 'config/universe example.json' --data-dir /path/to/private/data --policy /path/to/private/sec-policy.json --alpaca-policy /path/to/private/alpaca-policy.json
```

Copy the policy examples to a private directory and confirm actual usage rights before enabling permissions. Configure `SEC_USER_AGENT` with a legitimate contact identity and the Alpaca credentials locally. IEX is a partial-market research feed, not an execution quote. The sample universe provides identifiers, not investment recommendations. Missing eligible price/share evidence means no candidate. Do not commit credentials or local databases. No real API request was made for this release's offline verification.

See [engineering review](docs/0.4.0%20Engineering%20Review.md) for model selection, tool coverage, limitations, acceptance gates and deployment sequence. Earlier architecture and verification reports remain historical records, not current live readiness claims.
