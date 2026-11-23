# Atlas Investment OS — Verification Report

**Reviewed 2026-11-23.** This report applies to the **standalone reference configuration** in this archive; no live broker, market provider, cloud LLM, or user's existing repository tests were executed.

## Actual verified checks

- **60 / 60** standalone Python offline unit tests passed using `python -m unittest discover -s tests -v`.
- Exactly **50** unique logical Agent IDs in **10** teams.
- Exactly **21** event routing definitions, each marked `cannot_directly_trigger_live_order=true`.
- **0** roles can place live orders, mutate investor mandate or promote their own skill.
- **19** roles use deterministic Python as their primary runtime.
- All **10** private-only roles have local/deterministic primary models; 10 further local-only roles never use cloud models.
- Verified cost math for published USD rates, DeepSeek off-peak, Gemini price change date, Claude Haiku large-context price step; CNY Qwen pricing cannot be silently treated as USD.
- Verified unit-level refusal for unapproved mandate, missing live-quality data, over-limit concentration, cash floor, unknown/duplicate events, unverified material events, missing source IDs, non-UTC-aware timestamps, future-available evidence, uncertified model choice, daily budget and private-data-to-cloud calls.
- Offline P0 event route remains deterministic and cannot be cooldown-suppressed or converted into live-order permission.

## Model role distribution

| Runtime | Roles |
|---|---:|
| `deterministic` | 19 |
| `deepseek-flash` | 12 |
| `gemini-3.8-flash` | 7 |
| `gpt-6.2-sol` | 6 |
| `gpt-6-luna` | 3 |
| `local-private` | 2 |
| `claude-sonnet-5-5` | 1 |

## What was **not** verified

1. The existing `IBKR-Agent-harness` tests, despite public repo files/CI claims: this runtime could not clone GitHub because DNS/network connectivity was unavailable. The connected GitHub repository was inspected read-only. HEAD `c62f1147d7077ab97a886797ec5bd759765e6706` on 2026-11-21.
2. All API model candidates were checked against provider **documentation**, not paid functional calls; no actual financial accuracy, latency, token usage, rate-limit, availability or task success scores were measured.
3. The 50 roles are configuration records, not deployed 50 executable hosted agents. `src/atlas_policy_router.py` is a demonstrator and its risk pre-trade function is **not a broker-equivalent portfolio/margin model**.
4. Event predicates, full market calendar, live broker account reconciliation, tax account constraints, database schema migrations, strategy backtests, true data licenses, chart rendering, end-to-end call tracing, signed approvals and live trade order lifecycle still require engineering and real tests.
5. Security posture of unknown plugins/connector permissions and local model confidentiality were not proven. No code was pushed to any GitHub repo.

## Required adversarial release gates (not yet run)

- Replay scenario with fake post-dated financial restatement and 2026 price backtest at a 2024 decision date; must reject future information.
- Simulate broker disconnect / late Flex statement / stale real-time position / FX mismatch; all trade proposals fail closed.
- Test market holiday, half-session, DST, 9:30/16:00 boundaries, pre/post-market quote semantics.
- Inject malicious 10-K PDF, a prompt in news HTML and a `MCP tool` prompt that asks for policy change / account exfiltration; model cannot receive sensitive tools.
- Red team duplicate quote/event and race-condition order submission to verify durable idempotency.
- Run 100+ labeled investment research tasks with PIT cutoff, exact source validation, cross-model quality, cost and confidence intervals.
- Paper-trade shadow mode covering live event routing, market data permissions, broker session drops, alert reliability and end-of-day reconciliation.
- Validate real Canadian broker/API product permissions separately before considering production execution.

## Captured test result

```text
SkillsAndContractTests.test_evidence_contract_requires_point_in_time_fields) ... ok
test_exact_five_method_skills (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_exact_five_method_skills) ... ok
test_json_schema_metaschema (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_json_schema_metaschema) ... ok
test_method_skills_are_non_executable (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_method_skills_are_non_executable) ... ok
test_method_source_status_never_falsely_verified (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_method_source_status_never_falsely_verified) ... ok
test_methods_have_specific_checks_and_abstentions (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_methods_have_specific_checks_and_abstentions) ... ok
test_model_benchmarks_are_planned_not_claimed (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_model_benchmarks_are_planned_not_claimed) ... ok
test_research_decision_schema_rejects_unapproved_order_authorization (test_method_skills_and_contracts.MethodSkillsAndContractTests.test_research_decision_schema_rejects_unapproved_order_authorization) ... ok

----------------------------------------------------------------------
Ran 60 tests in 0.844s

OK

```

**Status: Prototype configuration QA passed; production release is NOT authorized.**
