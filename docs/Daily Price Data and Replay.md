# Daily price data ingestion and reference replay

The PA_Agent-inspired A065 route now has an actual provider adapter, not just
an OHLCV input schema. It uses Alpaca's documented v2 historical bars endpoint
(https://docs.alpaca.markets/us/reference/stockbars) with explicit IEX feed,
split adjustment and disabled symbol remapping. It does not claim consolidated
market volume or an executable price. It requires a rights-reviewed operator
policy binding one symbol to one security identifier, and explicit network
consent. Credentials remain in the operator environment, never in the ledger.
NYSE exchange-calendar dates, local-midnight timestamps and all expected
sessions are checked before any rows are written. Only prior complete New
York calendar days are accepted; daily aggregates may contain eligible prints
outside regular market hours. Missing bars, renamed symbols, holidays with
unexpected rows, incomplete pagination and malformed data cause rejection.

Install optional calendar dependencies and set ALPACA_API_KEY and
ALPACA_API_SECRET on your private runtime. Example rights policy (verify rights
and issuer mapping before use; this is not an entitlement grant):

```json
{"license_id":"ALPACA_PERSONAL","permitted_for_personal_analysis":true,"allow_local_retention":true,"cloud_allowed":false,"symbol":"EXAMPLE","security_id":"CIK:1","symbol_mapping_reviewed":true,"allow_historical_research":true}
```

```bash
atlas-daily-bars --data-dir /private/atlas --policy /private/bars-policy.json --start YYYY-MM-DD --end YYYY-MM-DD --network --retrospective
```

Use 61–200 sessions; retrospective requires at least 100. All observations
are private evidence with actual receipt time, not historical availability.
The retrospective module deliberately does NOT construct a fake historic
ledger. It uses the same fixed 61-bar feature window with no future values
in the signal calculation. For fixed 5/20-observation outcome windows it
compares next-observation close to later close; windows are disjoint within
each horizon. Reports show every observation and group sample sizes. This
is descriptive reconstructed price history, not an investable total-return
or point-in-time strategy backtest. It excludes dividends, costs and execution
assumptions. Small samples and repeated research inspection prevent any alpha
or probability certification.

For daily maintenance, supply an array of up to 20 policies as
daily_bar_policies in the private maintenance JSON, and add --roles pointing
to the existing 50-role manifest. The job refreshes the prior 180 calendar
days and runs the actual A065 RoleExecutor via RoleJournal, recording local
reference receipts and episode metadata. The same UTC-day slot is not
retried blindly. No scheduler is installed; operator deployment is required.

Existing watch continuity uses a self-hashed research plan; it is not proof of
a signed prior recommendation, and split-adjusted history can be revised.
Do not interpret its level touches as executions. Live API connectivity,
actual rights, broker coverage, historical archive validation, production
scheduler installation and independent role certification are not established
by fixture tests.
