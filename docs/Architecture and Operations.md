# Atlas Investment OS 2.0 — Institutional Architecture and Model Operations Blueprint

> **Status (2026-11-23):** Research-grade reference design and testable **offline configuration prototype**, not a production trading system and not a deployed update to the user's GitHub repository. Real orders are impossible in this reference package.

## 1. Executive architecture decision

Create 50 **logical competencies** organized in 10 divisions, with 5–7 model backends and a deterministic, human-controlled investment mandate. **Never schedule all 50 agents continuously.** A high-volume event intake and pricing monitor should be pure Python/SQL; the LLM is invoked only after authenticated events, sufficient point-in-time evidence, and a latency/cost justification. High-quality financial decisions require correctness, independence, and reproducibility rather than role count.

**Objective hierarchy:** (1) No execution without valid investor authority, (2) preserve trustworthy data and account state, (3) respect immutable owner risk limits, (4) seek incremental risk-adjusted benefit over an appropriate passive benchmark after all expenses, (5) minimize model cost subject to verified task-level quality. Target return is an objective, not a guaranteed constraint; max drawdown budget is a plan, not a guarantee that market losses cannot exceed it.

## 2. Current repository: verified static facts vs unverified operations

Read-only GitHub inspection: `RyanYang053/IBKR-Agent-harness`, default branch `main`, HEAD **`c62f1147d7077ab97a886797ec5bd759765e6706`** at inspection; commit timestamp **2026-11-21T19:49:33Z**. README / IMPLEMENTATION / source files describe a local-first, read-only IBKR agent harness, 7 structured workflows, multi-account ledger, DCF and reverse DCF, 37 MCP tools, Kelly/covariance/factor risk, FTS5 knowledge memory, and approval-aware research journals. Read the repository's own tests and CI artifacts before attributing real operational success to them. **Important limitation:** GitHub direct clone was unavailable in this container, so no tests from the existing repository were executed here. The 43 passing tests apply only to this standalone reference package, not the original broker stack.

Integration strategy: Preserve the existing `finance.py`, `market.py`, `decision.py`, `quant.py`, `knowledge.py`, `ops.py`, `server.py` and acceptance tests as the authority for existing deterministic features. Add a broker-isolated event bus, model registry/agent registry, evidence library, evaluation laboratory, bounded scheduling, budget ledger, and risk policy manager as separate modules. Avoid wholesale replacement.

## 3. Ownership and risk mandate

User/owner defines: investment horizon, risk capital, financial constraints, cash needs, target returns (non-binding), allowed account classes, currency, investment philosophy preferences, leverage permissions, maximum concentration, drawdown alarm levels, and order permissions. AI may optimize candidate strategies *inside* those bounds. Model instructions, retrieved documents, agent consensus, learned skills, and evaluation runs cannot change the owner's policy. Only a separate operator-authenticated configuration workflow may propose a versioned policy revision; human authorization must be externally verifiable and stored with hash/time/reason.

There are three distinct documents:

1. `Investor Objectives`: return aspirations, goals, benchmark, horizon.
2. `Investment Policy Statement`: hard risk ceilings, prohibited markets, trade permissions, concentration, leverage, liquidity floor and acceptable drawdown alerts.
3. `Strategy Charter`: preferences for quality/value/earnings/events/dip buying, strategies and their validation state.

If 20% expected CAGR conflicts with 15% max tolerated drawdown, the risk limit wins. Either revise the aspiration with user involvement or abstain. No agent can manufacture feasible performance.

## 4. Privilege design vs model intelligence

**Error consequence tiers (not risk appetite):**

- `low`: summarization/formatting only; factual claims still source-backed.
- `medium`: research and hypotheses; not allowed to create active order plans.
- `high`: evidence-dependent valuation, probabilistic judgement and draft investment recommendations; mandatory independent review.
- `critical`: account data, tax, margin, policy, historical backtesting controls, and math audit. **The enforcement decision must come from deterministic validated code, not an LLM vote.**

All 50 roles have `can_place_live_orders=false`, `can_change_investment_policy=false`, and `can_promote_strategy=false`. Any production execution adapter is a separate privileged service. Research role counts do not imply permission counts.

## 5. Model assignment principles

Use a fixed model ID (not mutable `latest` alias) to support audit and pricing. API model prices verified on 2026-11-23; refresh them automatically via provider-approved mechanisms and alert on drift before dispatching work. Actual financial model suitability must be established using your own evaluation set, not generic benchmark ranks.

**Suggested baseline:**

- $0 model: `deterministic` for price arithmetic, ledger, tax, statistics, backtests, hard risk and authorization.
- Cheap text: `gpt-6-luna` ($0.10/$0.50) for classifications and structured text; compare `claude-haiku-5-5` (same rate at ≤100K context) and `deepseek-flash` ($0.15/$0.60 off-peak; $0.30/$1.20 at peak). API prices are USD per million uncached input/output tokens.
- Long public research: `gemini-3.8-flash` ($0.75/$3.75 through 2026-12-31; $1.50/$7.50 from 2027-01-01). Compare against DeepSeek flash on extracted evidence and hallucination rate. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion. Optional unselected challengers: `gemini-4-hydrogen` ($1.50/$7.50 as checked) and `qwen3.8-flash` (official global pricing CNY 0.8/2.7 per million tokens, **not** USD). Their task-level performance and billing region must be verified before any role promotion; CNY price is deliberately blocked from the USD estimator without an authenticated FX conversion.
- Investment synthesis: `gpt-6.2-sol` ($2/$10), with medium effort default; escalate only when uncertainty or contradiction warrants additional reasoning.
- Cross-provider Red Team: `claude-sonnet-5-5` ($2/$10), medium/high effort only for major positions, not every headline.
- Exceptional research: `gpt-6.2-astra` ($8/$40), limited by monthly cap and only if the expected value of incremental evidence justifies cost. It is not a trader, arbiter of policy, or authorization authority.
- Local private: existing local `Strata Gyro-M` route is **conditionally suggested** until privacy, latency, context, and finance-eval benchmarks pass. Model API cost may be zero, but hardware, power, and maintenance are not.

Current independent general-purpose model testing shows GPT-6.2 Sol as a plausible price/performance compromise on some tasks; it is not evidence of forecasting alpha. Allow offline cached batch analysis for slow tasks, never for immediate risk checks.

### 5.1 Financial task-specific model evaluation

Eval sets must include at least: verified SEC sentence extraction, statement normalization, identifying changes in management guidance, missing evidence abstention, ownership of numbers/sources, tool output schema compliance, prompt injection, contradiction handling, consistent answer under paraphrase, quantitative hallucination detection, risk reasoning, cost, latency, and repeated-call variance. The candidate fallback must pass the *same* criteria as the primary on the *same* task class; do not simply pick the cheapest model because its benchmark rank looks acceptable.

For a financial advice-eligible recommendation, the deterministic calculations must tie out exactly, material sources must be present and correctly dated, no hard policy violations may exist, and the independent risk gate must accept it as a recommendation. Do not use model confidence alone as permission.

## 6. Full fifty-role registry

`A##` is a stable logical role ID. Model assignment is a baseline **hypothesis**, subject to the role's benchmark certification. D = deterministic; LOCAL = private local model; LUNA = GPT-6 Luna; DS = DeepSeek Flash; GEM = Gemini 3.8 Flash; SOL = GPT-6.2 Sol; SONNET = Claude Sonnet 5.5.

| Agent | Department | Specialty | Default runtime | Error impact | Data boundary |
|---|---|---|---|---|---|
| A011 | CIO & Governance | CIO Orchestrator | SOL | high | public_only |
| A012 | CIO & Governance | Investment Policy Supervisor | D | critical | private_only |
| A013 | CIO & Governance | Research Task Planner | DS | medium | public_only |
| A014 | CIO & Governance | Evidence Quality Controller | LUNA | high | public_only |
| A015 | CIO & Governance | Investment Committee Secretary | LUNA | low | public_only |
| A021 | Financial Data Intelligence | Market Feed Validator | D | critical | local_only |
| A022 | Financial Data Intelligence | SEC & XBRL Normalizer | D | high | public_only |
| A023 | Financial Data Intelligence | News & Event Verifier | DS | high | public_only |
| A024 | Financial Data Intelligence | Cross-Provider Reconciler | D | critical | local_only |
| A025 | Financial Data Intelligence | Privacy and Lineage Auditor | D | critical | local_only |
| A031 | Fundamental Research | Business Model Analyst | GEM | medium | public_only |
| A032 | Fundamental Research | Revenue and Unit Economics | DS | high | public_only |
| A033 | Fundamental Research | Competitive Moat Analyst | GEM | high | public_only |
| A034 | Fundamental Research | Management and Capital Allocation | DS | high | public_only |
| A035 | Fundamental Research | Accounting Forensics Analyst | SOL | high | public_only |
| A041 | Valuation Research | Institutional FCFF DCF Analyst | D | high | local_only |
| A042 | Valuation Research | Reverse DCF Analyst | D | high | local_only |
| A043 | Valuation Research | Comparable Companies Analyst | GEM | medium | public_only |
| A044 | Valuation Research | Scenario and Probability Analyst | SOL | high | public_only |
| A045 | Valuation Research | Options Valuation Analyst | D | high | local_only |
| A051 | Investor Wisdom Council | Buffett-Graham Quality Value | GEM | medium | public_only |
| A052 | Investor Wisdom Council | Munger Inversion and Bias | DS | medium | public_only |
| A053 | Investor Wisdom Council | Howard Marks Cycles | DS | medium | public_only |
| A054 | Investor Wisdom Council | Damodaran Story-to-Numbers | SOL | high | public_only |
| A055 | Investor Wisdom Council | Dalio Macro Regimes | GEM | medium | public_only |
| A061 | Macro & Market Intelligence | Rates & Credit Conditions | DS | medium | public_only |
| A062 | Macro & Market Intelligence | Liquidity and Financial Conditions | DS | medium | public_only |
| A063 | Macro & Market Intelligence | Inflation & Growth Releases | LUNA | medium | public_only |
| A064 | Macro & Market Intelligence | FX and Commodities | DS | medium | public_only |
| A065 | Macro & Market Intelligence | Market Regime Classifier | D | high | local_only |
| A071 | Quantitative Research | Factor Discovery Researcher | DS | medium | public_only |
| A072 | Quantitative Research | ML Feature and Leakage Auditor | SOL | high | public_only |
| A073 | Quantitative Research | Event Study Researcher | DS | medium | public_only |
| A074 | Quantitative Research | Alternative Data Researcher | GEM | medium | public_only |
| A075 | Quantitative Research | Walk-Forward Backtest Auditor | D | critical | local_only |
| A081 | Portfolio and Risk | Concentration and Exposure Auditor | D | critical | private_only |
| A082 | Portfolio and Risk | VaR CVaR Tail-Risk Engine | D | critical | private_only |
| A083 | Portfolio and Risk | Robust Kelly Position Sizing | D | critical | private_only |
| A084 | Portfolio and Risk | Stress Testing and Hedge Research | LOCAL | high | private_only |
| A085 | Portfolio and Risk | Tax and Account Location Check | D | critical | private_only |
| A091 | Trade Operations | Order Proposal Composer | LOCAL | high | private_only |
| A092 | Trade Operations | Liquidity Slippage Analysis | D | critical | local_only |
| A093 | Trade Operations | Leverage and Margin Monitor | D | critical | private_only |
| A094 | Trade Operations | Fill and Reconciliation Auditor | D | critical | private_only |
| A095 | Trade Operations | Execution Authorization Gateway | D | critical | private_only |
| A101 | Independent Audit and Learning | Bear Case Red Team | SONNET | high | public_only |
| A102 | Independent Audit and Learning | Financial and Source Audit | SOL | critical | public_only |
| A103 | Independent Audit and Learning | Causal Bias and Confounding | GEM | high | public_only |
| A104 | Independent Audit and Learning | Forecast Calibration Engine | D | critical | local_only |
| A105 | Independent Audit and Learning | Skill Improvement Researcher | DS | medium | public_only |

Each role emits a typed output with: event IDs, citation IDs, model ID and effort, immutable input snapshot hash, assumptions, counterarguments, unknowns, recommendation/status, cost, confidence with calibration method (if available), and evaluation version. A public model never receives raw broker account data. If context is private, create a local-only analysis or a deliberately sanitized, audited, non-reversible aggregate for public research.

## 7. Dynamic control flow

`Raw Feed → Deterministic Intake → Event Dedup/Fact Verification → Materiality Score → Role Planner → Parallel Independent Research → Math Engines → Red Team → Decision Contract → Independent Risk Gate → Owner Review → Journal → Outcome Scheduler`.

Minimum role activation: ordinary classification 0–1 model; full company research 4–8; decision with real capital at risk 8–15; complex high-impact research up to 20–35; maximum 50 only in an explicit broad committee exercise. Pure math/risk roles are invoked as functions, not as repeated LLM prompts. Red Team receives independent evidence snapshot before seeing optimistic investment conclusions where feasible.

A task escalates only if (a) material unknowns remain, (b) sources conflict, (c) risk/capital at stake is large relative to the owner's approved policy, (d) base/bear valuations are especially assumption-sensitive, or (e) cheap and premium models disagree on a testable claim. Otherwise stop early.

### 7.1 Priority-based events

The accompanying `event rules.json` defines 21 event types with P0–P4 priority. **P0 always invokes the independent deterministic precheck regardless of LLM quotas or event cooldown.** The event manifest is a route map and does **not** contain the real provider-specific event detectors. Any P1/P2 event must be externally verified and have a unique source event ID before advisory analysis is admitted. Price drops alone never submit trades.

| Event ID | Priority | Role IDs | Initial cooldown | Source class |
|---|---|---|---|---|
| `margin_cushion_breach` | P0 | A081, A082, A093 | 0 s | broker_metrics |
| `portfolio_data_inconsistent` | P0 | A021, A024, A081 | 0 s | ledger |
| `market_data_stale` | P0 | A021, A024 | 0 s | feed_quality |
| `approval_expired` | P0 | A092, A095 | 0 s | execution_state |
| `unauthorized_policy_change` | P0 | A012, A025 | 0 s | policy_guard |
| `execution_reconciliation_error` | P0 | A093, A094 | 0 s | broker |
| `filing_material_risk` | P1 | A023, A034, A035, A101, A102 | 3600 s | sec_filing |
| `management_change_verified` | P1 | A023, A034, A042, A101 | 3600 s | official_IR |
| `guidance_withdrawal` | P1 | A023, A032, A042, A101 | 3600 s | official_IR |
| `earnings_release` | P2 | A022, A032, A041, A042, A043, A101 | 3600 s | earnings |
| `valuation_entry_zone` | P2 | A041, A042, A044, A083 | 1800 s | price_and_thesis |
| `market_volatility_threshold` | P2 | A065, A081, A084 | 900 s | price_and_vol |
| `macro_event_release` | P2 | A063, A065, A081 | 1800 s | macro_calendar |
| `material_news` | P2 | A023, A031, A101 | 1200 s | news_verified |
| `stock_anomaly` | P3 | A021, A023, A033 | 1800 s | price_volatility |
| `daily_portfolio_digest` | P3 | A011, A081, A082 | 86400 s | schedule_nyse |
| `weekly_research_triage` | P3 | A013, A071, A073 | 604800 s | schedule_weekly |
| `weekly_postmortem` | P4 | A104, A105 | 604800 s | schedule_weekly |
| `monthly_attribution` | P4 | A074, A075, A104 | 2592000 s | schedule_monthly |
| `quarterly_thesis_review` | P4 | A031, A035, A054, A105 | 7776000 s | schedule_quarterly |
| `strategy_candidate_proposed` | P4 | A075, A102, A104, A105 | 604800 s | strategy_experiment |

### 7.2 Trigger predicates — definitions that must be separately implemented and calibrated

- Margin: compute excess liquidity / NAV, maintenance margin distance, margin cushion under scenario shocks and collateral concentration, with broker-account-specific rules. Example warning values must be approved per account; do not assume a universal 5% or 10% threshold.
- Price and volume: z-score of same-horizon returns, ATR, abnormal volume, liquidity, and corporate action checks; use preliminary `abs(z)>=2` only to queue a *review*, never an order. Backtest alert precision and false-positive costs.
- Valuation: a **new, qualified** reference quote entering an investor-approved discount band triggers a DCF freshness check, not an immediate buy.
- Earnings: verified issuer release/filing event ID, period, timestamp, guidance changes; potential non-trading hours considered.
- Macroeconomics: official release calendar, actual-surprise vs then-known consensus, revision vintages, factor-level transmission to holdings.
- Broker: every executed trade or transfer triggers position/cash/tax-lot reconciliation; severe mismatch blocks all new order proposals.
- Model drift: recurring audited error or changed model revision triggers a fresh validation cycle.

**De-duplication** uses `(event_type, instrument_id, source_event_id)` and a durable idempotency record. P0 cannot be suppressed by cooldown; non-critical events may be grouped. Use actual market calendars with holidays, half-days and DST, not `weekday()<5` alone.

## 8. Cadence

- Every quote and broker update: deterministic validation, no LLM by default.
- Intraday every 1–5 minutes: state/freshness and risk pulse; apply API rate limits, never poll all data if a streaming subscription is used.
- At 07:30 ET (trading days): validate prior-close broker records, corporate actions, data health.
- 08:15 ET: preliminary macro/earnings/calendar + overnight summary.
- 09:15 ET: pre-market valuations and portfolio constraint health.
- 09:30–16:00 ET: event-driven, rate-limited review (not mandatory LLM polling).
- 16:15 ET: preliminary close; label as preliminary until vendor finalization.
- 20:00 ET: daily research summary and next-session watch conditions.
- Weekly: error review, thesis status, forecast resolution, emerging candidate priority.
- Monthly: model calibration, factor exposures, capital deployment regret versus alternatives, AI/model token spend.
- Quarterly: full living-thesis refresh, new investor skill citations, regime validation and backtest roll-forward.
- Annually: investment policy review **for owner approval**, audit of risk settings and data contracts.

Never assume a fixed clock is the true release time for all data; official exchange/issuer/provider calendars and vendor availability timestamps determine eligibility.

## 9. Data, identity and provenance

Use canonical issuer `CIK`, IBKR `conid`, FIGI/ISIN where available, and effective-dated mappings for tickers, share classes, options, corporate actions, ADRs and delisted securities. Separate `event_time`, `source_published_at`, `ingested_at`, and `available_at`; all backtests must filter `available_at <= decision_time`. Keep revision history for macro releases (ALFRED vintage), financial restatements, issuer guidance and consensus estimates. Store original licensed raw documents immutable with content hashes and reference URLs.

Data state machine: `RAW → PARSED → SOURCE_VALIDATED → CROSS_CHECKED → ELIGIBLE → STALE/REVOKED`; no unstamped raw data can enter a trading recommendation. A stale quote cannot produce current price upside. During market closures, call the quote `last_regular_close` or `prior_close` with as-of metadata, not live.

Data categories: broker ledger and positions, public-market prices, company filings/XBRL, official earnings calls/IR, macro/FX, company action master, optional licensed estimates/consensus, future point-in-time research warehouse. Exact dividend/split adjustments, multi-currency FX basis, short-sale availability and tax-lot rules must be tested across both accounts and broker records.

## 10. RAG and memory

Six repositories: (1) authoritative source documents, (2) investment philosophy skills with provenance and licensing, (3) company/industry relationship graph, (4) timestamped decisions and rejected alternatives, (5) mistakes and outcomes as **hypotheses**, (6) versioned validated strategies and models.

Retrieval: exact symbol/entity disambiguation → source authority filter → point-in-time filter → lexical + vector hybrid retrieval → optional reranking → numeric fact lookup in structured warehouse → contradiction and support coverage audit → citation-linked evidence package. Chunk by meaningful sections and tables, not only character count. Avoid treating search result snippets as accounting records. Secure untrusted retrieved content against prompt injection, HTML/instruction laundering and tool exfiltration.

Memory lifecycle: `proposed fact/lesson → cited source → prospective impact estimate → evaluation → operator approval → versioned active rule → periodic expiry / rollback`. Never mutate old predictions with future outcomes. Do not let profitable results automatically become generic trading skills.

## 11. Quant and portfolio pipeline

Use the existing deterministic driver-based FCFF and reverse DCF as the starting point, but force provenance and unit checks for each assumption: revenue drivers, operating margins, tax, D&A, capital expenditure, working capital, WACC, terminal growth/exit EV, net debt, dilution/SBC and FX. Show bear/base/bull, sensitivity and market-implied assumptions. Reverse DCF is not itself a future-return probability.

For probability outputs, define an explicit dated terminal event (e.g. 12-month total return), estimate regime-conditional outcome distribution and alternative benchmarks, then calibrate against historical predictions. Touch/first-passage probability, expiration terminal probability, risk-neutral option distribution, and subjective real-world probability must remain separate.

For Kelly, compute expected *log wealth* across all conditional scenarios with commissions/slippage/FX/financing costs, cap at 25% of robust theoretical Kelly at most unless separately approved, and always constrain by confidence interval uncertainty, correlated exposures, multiple account positions, tail losses and capacity. When no credible edge is demonstrated, **WAIT** is a valid outcome.

Combine leveraged ETF exposures using daily-reset behavior, not naïve static 3x over long periods. Model options delta/gamma/vega and gap risk, expiry, assignment, liquidity and financing/margin stress. Separate cash, available funds, buying power, excess liquidity and NAV.

## 12. Independent authorization gateway

`BrokerScope` is a separate process with no LLM credentials and with an allowlist of account+asset+market permissions, verified limit orders only, maximum notional/position/risk, broker contract ID, exchange and trading hours, authenticated owner approval, expiry TTL, nonce, anti-replay idempotency, two-phase preflight and fresh broker re-read. For this personal reference architecture **it remains disabled**. Staging or approval of an analysis memo is not an execution authorization. Risk gateway never takes a bypass instruction from an LLM response.

P0 conditions: missing account, stale quote, cross-account discrepancy, excessive leverage/correlation/margin risk, data integrity failure, cloud leakage, prompt injection or hash mismatch must halt any future order proposal at least until verified by humans and independent controls.

## 13. Strategy evaluation and self-improvement

Use chronological, point-in-time simulation with exchange calendar, split/dividend adjustments, delisting, spreads, realistic fill assumptions, taxes, FX, funding and historical liquidity. Evaluate on raw return, matched QQQ beta, equity-factor risk, drawdown/CVaR, turnover, transaction-cost drag, FDR/multiple testing and change across market regimes. Introduce permanent holdout or forward-only paper/shadow window before promotion.

Outcome chain: `frozen forecast → realized event → Brier/log loss/calibration by bucket → investment vs passive alternative → counterfactual execution → mistake candidate → controlled experiment → champion/challenger → owner approval / rollback`. A successful trade does not prove correct reasoning; a losing trade does not imply the process was flawed.

## 14. Budget controls

File `operating budget.json` gives **provisional** soft/hard daily caps $5/$12, monthly $100/$150, 6 concurrent LLM calls, and at most 12 Astra calls/month. These are *examples only*, not actual user consent. When budget is exceeded: stop low/medium research, continue deterministic risk/account reconciliation and owner alerts. Repeated provider errors must fail closed on recommendations. Pricing drift can invalidate a budget admission result. Track input/output, cached/uncached, thinking tokens, retries, tool/search charges, rate limits, provider, and USD/CAD conversion.

Monthly sample (15,400 LLM calls, deliberately high-activity and **hypothetical**): 10,008 Luna (3k/600 tokens) $6; 4k DeepSeek Flash (8k/1.2k, peak) $15.36; 1k Gemini 3.8 Flash (20k/3k) $26.25; 300 Sol (25k/4k) $27; 80 Claude Sonnet (25k/3.5k) $6.80; 12 Astra (30k/5k) $5.28 = **$86.69/month**. Excludes market data, compute, paid searches, tool calls, FX, retries and cache. This is not a promise or observed bill.

If the portfolio were $75,000, even $50/mo operating cost would equal $600/year, or **0.8% of NAV annually** before taxes and market-data fees. Require a measurable expected *incremental* benefit or reduce the research footprint.

## 15. Production checklist and explicit incomplete areas

**Offline reference pack:** manifest cardinality, model registry, non-authority rules, privacy, cooling, verified event IDs, model-eval admissions, token price calculations, daily budget and research gate are tested.

**NOT tested and necessary before production:** user's live brokerage account completeness; account roles and tax semantics; vendor API permissions and keys; official market calendar integration; authentication and HMAC/nonce policy approvals; true event detectors; exchange/data licensing; end-to-end full financial model checks; live or paper trade order-state idempotency; alert delivery with failure recovery; real disaster-recovery drills; PII isolation across cloud routes; RAG prompt-injection adversarial evaluation; financial benchmark comparison with actual model calls; time-series backtests and model drift; no-loss guarantee impossible.

## 16. Implementation sequence and release gates

- **G0 Data contract:** canonical identifiers, timestamps, corporate actions, source lineage; comparison to broker statements.
- **G1 Safe orchestration:** integrate 50-role manifest and bounded planner with repo's `ops.py`; no tool writes; telemetry and budget limits.
- **G2 Finance truth:** DCF/reverse, probability vs price target, tax, cash/SGOV, leverage overlap, stress tests, reproducible evidence IDs.
- **G3 Research quality:** independent source/audit benchmark with ≥100 locked, labeled tasks including no-answer cases, dated backtests, injection tests and adversarial price/filing errors.
- **G4 Learning loop:** shadow tests, forecast outcome maturation, challenger promotion after prospective evidence and signed owner approval.
- **G5 Live execution consideration:** only after independent security testing, broker rules, legal limits, verified alerts, disaster recovery and explicit owner opt-in; do not enable it by default.

Each gate must include a *fail-closed* rollback path; never promote a model, Skill, or risk threshold based only on an unreviewed backtest.

## 17. Authoritative external reference links (checked 2026-11-23)

- OpenAI model catalog and pricing: https://developers.openai.com/api/docs/models ; https://developers.openai.com/api/docs/pricing
- Anthropic model catalog and pricing: https://platform.claude.com/docs/en/models/overview ; https://platform.claude.com/docs/en/about-claude/pricing
- Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing/
- DeepSeek official model and pricing: https://api-docs.deepseek.com/quick_start/pricing/
- Alibaba Qwen current offerings: https://help.aliyun.com/zh/model-studio/text-generation-model/
- Independent general benchmark: https://artificialanalysis.ai/leaderboards/models (not a finance-alpha benchmark)
- IBKR API market data limitations: https://www.interactivebrokers.com/support/faq/content/get-real-time-data-us-1491290694
- Public research on financial agents evaluation: https://arxiv.org/abs/2603.27539 ; https://arxiv.org/abs/2512.02261 ; https://arxiv.org/abs/2611.07464
- User repository: https://github.com/RyanYang053/IBKR-Agent-harness


## 18. Existing investment plugin workflow integration (conditional)

The installed Public Equity Investing plugin's router lists specialists for `company-tearsheet`, `financials-normalizer`, `dcf-model-builder`, `three-statement-model-builder`, `comps-valuation`, `portfolio-risk-management`, `scenario-sensitivity-generator`, `model-audit-tieout`, `earnings-deep-dive`, `thesis-tracker`, `catalyst-calendar`, `long-short-pitch` and `memo-builder`. The Atlas role planner should **map capabilities**, not blindly copy/activate platform-specific plugin code. Access is adapter-specific, requires invocation/authorization and successful read-only capability checks at runtime. Existing personal Investment Skills remain in place and may be superseded only after tests. Investor wisdom skills should cite original public materials, use documented method rather than persona imitation, and respect publishing/content licenses.

## 19. Observability and skill release policy

For each event, persist `trace_id`, dedupe/idempotency key, source snapshot IDs, evidence URI/content digest, provider model **snapshot** and reasoning setting, agent config revision, tool permissions, cached/uncached token counts, rate sheet revision, p50/p95 latency, verifier results, math engine version, final decision state, and follow-up due date. Private holdings and account identifiers must be redacted or encrypted in traces. Budget monitor controls model spending; it must not suppress safety checks.

New experimental Skills are signed as proposed, get deterministic unit tests and historical blind tests, then paper/shadow monitoring, and only then can enter an approved registry. The formal investment mandate remains versioned and owner-controlled. The model can suggest a 20% CAGR goal is incompatible with a hard loss tolerance, but cannot change risk constraints itself.

## 20. Draft investor method Skills (five packaged, unverified evidence ingestion)

The archive includes five example decompositions: Buffett-Graham quality/value, Munger inversion, Howard Marks cycles, Damodaran story-to-numbers, and Dalio macro diversification. Each provides a manifest, applicability checklist, evidence candidates, abstention conditions and required tests. **None is promoted to active trading or represents the named person's current advice.** Online primary sources are candidates for licensed ingestion and quotation checking; the archival knowledge extraction is not yet done. Skill files are drafts, and their provenance `sources_ingested_and_verified=false` is explicit. Skills must be evaluated on cases dated before the test prediction to prevent future knowledge leakage.

## 21. Typed evidence and decision contracts

`schemas/evidence record.schema.json` requires source provider/document ID, event/published/available/ingested timestamps, digest, license and validation state. `schemas/decision contract.schema.json` requires a versioned mandate, source snapshot IDs, math engine version, contradiction/unknown/falsifier lists, status, risk audit and explicit immutable `can_place_live_order=false` and `can_override_policy=false`. For real operation, validation of UTC/chronology, proper numeric units and source IDs must happen in code beyond basic JSON Schema; schema validation alone cannot prove factual truth or financial correctness.

## 22. Model challenger tournament: designed but not executed

`config/model evaluation plan.json` proposes 10 locked task classes, at least 100 cases per task, and proper source-correctness, numeric exactness, risk safety, latency and cost scores. Models must be compared using the same task inputs, snapshots, reasoning settings and tool permissions, with nondeterministic repeats and a holdout. The plan is **not** evidence that any vendor model has passed the finance benchmarks. Champion/fallback promotion is disabled until task certifications are recorded by an authorized operator.

## 23. Practical release priority

1. Add deterministic release gates and PIT source contracts with immutable owner mandate.
2. Integrate real authenticated event streams and market/broker calendars.
3. Connect role planner with per-task model certification; run actual model APIs on controlled public financial evals.
4. Populate licensed source library and verify each method Skill.
5. Perform historical and forward paper/shadow tests, chaos/injection, broker disconnect and full-account reconciliations.
6. Keep execution disabled unless a completely separate approved broker integration and user authorization exists.
