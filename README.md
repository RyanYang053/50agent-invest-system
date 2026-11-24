# Atlas Investment OS — research and controlled paper pilot 0.6.0

A local-first investment research system with 50 logical specialist roles and 21 event routes. **No live order submission or AI modification of owner risk policy.** Separate operator-only paper pilot; no Agent can send orders. The existing IBKR-Agent-harness is not modified.

## Quick start (from repository checkout)

```bash
python -m pip install -e '.[market_calendar,test,quant]'
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

## Controlled paper pilot

```bash
python -m atlas_pro.paper_replay
```

The offline replay uses fictional prices and a fictional instrument. For a dedicated Alpaca paper account, follow [Paper Pilot Runbook](docs/0.5.0%20Paper%20Pilot%20Runbook.md). The paper gateway is disarmed by default, fixed to the Alpaca paper host, and requires a locally confirmed policy, dedicated paper keys, account ID match, cash-only limits, and explicit operator approval for every order. IBKR remains read-only. Do not use real brokerage credentials, commit private files, or register the paper gateway as a model tool.

The broker paper adapter has been tested against provider-shaped fixtures, not an authenticated broker session. No actual simulated broker orders have been sent. Research WAIT decisions are not automatically converted to orders.

## Open-source-informed research workflow (0.6)

See [Open Source Fusion](docs/0.6.0%20Open%20Source%20Fusion.md) for the executable research packet workflow, upstream integration catalog, 50-role coverage map, exact evidence lookup, sector ranking, independent cash-equity risk, optional SciPy CVaR optimization, locked RAG evaluation and external experiment result contract. `atlas-workflow` is research-only and always waits rather than emitting orders. External Qlib, RD-Agent, LEAN, Docling, skfolio and other engines are not installed or certified by this release. Existing paper pilot is unchanged and requires explicit operator consent per order.
