# LEAN engine execution fixture

This adds an actual-engine development acceptance case using QuantConnect LEAN
rather than trusting an imported NAV curve. It is not a general-purpose
backtest or a live trading route.

Upstream interface references:
- https://github.com/QuantConnect/Lean/blob/master/Launcher/config.json
- https://github.com/QuantConnect/Lean/blob/master/Dockerfile
- https://github.com/QuantConnect/Lean/blob/master/Data/equity/readme.md
- https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment

The fixed algorithm uses a fictional equity ATLASFICT on Jan 2–3, 2020.
Twenty generated minute bars are constant at 100 USD and 110 USD respectively.
There are no corporate actions. It simulates buying 10 and selling 10,
with a constant USD 1 fee per order and zero slippage. The receipt records
actual LEAN order events, observed bars, final position, cash and NAV.
An independent decimal calculation requires 10,098 USD cash/NAV, zero
position, two fills, and USD 2 fees. Missing/conflicting/malformed receipts
fail the test. No broker data or real market data is needed.

For an operator-reviewed local LEAN image ID:

```bash
python -m pip install -e '.[test]'
image=$(docker image inspect --format '{{.Id}}' quantconnect/lean:YOUR_REVIEWED_TAG)
bash sandbox/run-lean-fixture.sh "$image" /private/lean-fixture-receipt.json
```

The fixed runner cannot accept arbitrary algorithm code or real data. The
image is resolved before running; the container is nonroot, read-only root,
network none, bounded memory/CPU/processes/runtime, and has only synthetic
fixtures mounted read-only. Temporary writes use a container tmpfs. No
broker credentials or writable repository/home/control socket mounts.
The trust boundary includes the operator-reviewed image, Docker/kernel,
and the committed algorithm. This is not a remote attestation scheme.

CI pulls the upstream latest tag solely for a developer reference run and
records the resolved digest/ID. That tag is mutable across runs; a production
image requires a pinned, reviewed upstream digest and dependency provenance.
CI must complete the actual engine run before it can be called verified.
The developer tests of the receipt verifier use explicit synthetic receipts
and are not substitutes for execution. The separate older normalized-equity
review path remains useful for independently reviewing licensed real
historical LEAN runs.

Outstanding: independently sourced real point-in-time data, corporate
actions, realistic bid/ask/slippage/capacity/settlement, benchmark matching,
and audited full-universe historical and prospective evaluation. No
investment performance or general engine correctness claim is made.
