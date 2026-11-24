<p align="center">
  <img src="docs/assets/banner.svg" alt="Atlas Investment OS — 50 specialist roles • Evidence-first research • Human control" width="100%">
</p>

# Atlas Investment OS

[English](README.md) · [简体中文](README.zh-CN.md)

**50 specialist roles. One auditable investment research workflow.**

Local-first research, valuation, quantitative analysis, risk and governance. The 50 roles are registered logical specialists, not 50 continuously running LLMs.

[Try the demo](#try-the-demo) · [Quick start](#quick-start) · [Documentation](#documentation) · [Roadmap](ROADMAP.md) · [FAQ](FAQ.md) · [Contribute](CONTRIBUTING.md)

[![CI](https://github.com/RyanYang053/50agent-invest-system/actions/workflows/ci.yml/badge.svg)](https://github.com/RyanYang053/50agent-invest-system/actions/workflows/ci.yml)
![Research only](https://img.shields.io/badge/live%20orders-disabled-555)

[![Stars](https://img.shields.io/github/stars/RyanYang053/50agent-invest-system?style=flat)](https://github.com/RyanYang053/50agent-invest-system/stargazers) [![Forks](https://img.shields.io/github/forks/RyanYang053/50agent-invest-system?style=flat)](https://github.com/RyanYang053/50agent-invest-system/forks)
[![Demo build](https://github.com/RyanYang053/50agent-invest-system/actions/workflows/public-demo.yml/badge.svg)](https://github.com/RyanYang053/50agent-invest-system/actions/workflows/public-demo.yml) [![Issues](https://img.shields.io/github/issues/RyanYang053/50agent-invest-system)](https://github.com/RyanYang053/50agent-invest-system/issues) [![Contributions](https://img.shields.io/badge/contributions-welcome-27845d)](CONTRIBUTING.md)

## Try the demo

No personal portfolio, API key or live brokerage session is needed. [Open the public demo workflow](https://github.com/RyanYang053/50agent-invest-system/actions/workflows/public-demo.yml), select a successful run from the branch you want to inspect, download its HTML preview artifact, unzip it and open `atlas-demo.html`. GitHub may require sign-in to download an artifact; artifacts expire. The source-checkout commands below work independently of GitHub artifact availability.

The demo is generated from fixture data, not a marketing mock-up, live market quote or financial performance claim.

## Quick start

```bash
git clone https://github.com/RyanYang053/50agent-invest-system.git
cd 50agent-invest-system
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\Activate.ps1` in PowerShell.

```bash
python -m pip install -e '.[market_calendar,test,quant,ml]'
python scripts/demo.py --output atlas-demo.html
```

Open the generated HTML file locally. The report runs the actual offline integration smoke and displays the role manifest. No broker or paid model calls; not a live agent trace.

## What you can do

| Area | Capabilities |
| --- | --- |
| Evidence | Point-in-time SEC normalization, source licensing and scoped retrieval |
| Valuation | FCFF DCF, reverse DCF, scenarios and conditional Kelly |
| Quant | Rolling training, fixed experiments and risk challengers |
| Workflow | Role-specific tasks, event routing, reviewed skills and private memory namespaces |
| Governance | Fail-closed checks and operator approval |

```mermaid
flowchart TD
 E[Licensed evidence] --> R[Scoped retrieval]
 R --> T[Specialist roles]
 T --> Q[Deterministic valuation and risk]
 Q --> G[Policy and evidence checks]
 G --> O[Research output / wait]
 H[Human operator] --> P[Separate paper pilot]
```

## Explore the roles

**50 roles across 10 teams.** See the [complete role catalog](docs/ROLE_CATALOG.md) for each role's scope, deliverable and review status.

| Team | Roles |
| --- | ---: |
| CIO & Governance | 5 |
| Financial Data Intelligence | 5 |
| Fundamental Research | 5 |
| Valuation Research | 5 |
| Investor Wisdom Council | 5 |
| Macro & Market Intelligence | 5 |
| Quantitative Research | 5 |
| Portfolio and Risk | 5 |
| Trade Operations | 5 |
| Independent Audit and Learning | 5 |

```bash
atlas-core catalog --roles "config/50 agent manifest.json"
atlas-core readiness
python -m atlas_pro
python -m atlas_pro.paper_replay
```

- [Role manifest](config/50%20agent%20manifest.json)
- [Capability packs](docs/0.18.0%20Employee%20Capability%20Packs.md)
- [Architecture and operations](docs/Architecture%20and%20Operations.md)
- [Verification report](docs/Current%20Verification%20Report.md)
- [Paper pilot](docs/0.5.0%20Paper%20Pilot%20Runbook.md)
- [Macro source refresh](docs/0.20%20Macro%20Source%20Refresh.md)

Research prototype: no live order submission. Paper pilot is separate, disarmed by default and operator-only. Offline fixtures do not prove returns, independent role competence, real-provider readiness or professional certification.

## Verification

```bash
python -m pytest -q
```

See [engineering reference](ENGINEERING.md) for the preserved previous technical documentation, [launch gates](docs/LAUNCH.md) and [license status](LICENSING.md).

## Documentation

| Resource | Start here |
| --- | --- |
| First use | [Quick start](#quick-start) |
| Technical detail | [Engineering reference](ENGINEERING.md) · [50-role catalog](docs/ROLE_CATALOG.md) |
| Frequently asked questions | [FAQ](FAQ.md) |
| Current plans and gaps | [Roadmap](ROADMAP.md) · [Vision](VISION.md) |
| Changes | [Changelog](CHANGELOG.md) |
| Security and privacy | [Security policy](SECURITY.md) |
| Licensing | [License status](LICENSING.md) |
| Contribution process | [Contributing](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Support](SUPPORT.md) |
| Releases | [GitHub Releases](https://github.com/RyanYang053/50agent-invest-system/releases) (check current availability) |
| Research reference | [Citation metadata](CITATION.cff) |

## Related projects

- [IBKR Agent Harness](https://github.com/RyanYang053/IBKR-Agent-harness) — Local-first Python and MCP toolkit for Interactive Brokers portfolio research, combining deterministic calculations, investment policy checks, valuation and persistent workflows with human approval.
- [IBKR Portfolio Analyzer](https://github.com/RyanYang053/ibkr-portfolio-analyzer) — Local-first desktop analytics for holdings, performance, risk and research.

These are separate projects, not a claimed integrated deployment.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). If the project is useful, consider starring it or reporting a reproducible improvement.

Research and educational use only; not financial or tax advice.
