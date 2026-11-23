# Atlas Investment OS 3.0 — Professional Engineering Readiness

**审计日期：2026-11-23。状态：可执行的本地研究与风控参考实现；尚未经过生产环境验收。**

> 本文不是收益承诺，也不是已经完成的真实交易系统。真实资金订单始终禁用。现有 IBKR-Agent-harness 没有被修改。

## 1. 这次确实落地了什么

与旧版 50 Agent 角色配置文件不同，本次新增了能够运行与测试的核心模块：

1. `atlas_pro.ledger`：SQLite WAL 证据登记、`published_at/available_at`、Point-in-Time 检索、修订父记录、来源与授权限制、内容哈希审计。防未来信息，不承诺对具有写入权限的管理员防篡改；强证据需要外部签名与备份。
2. `atlas_pro.retrieval`：SQLite FTS5 原始来源引用和日期门控、本地/公开空间分离、可选离线向量融合接口、内容不可信标记；**未实际下载或加载 Qwen Embedding，也未部署 Qdrant**。没有 embedding 时是关键词 BM25 检索，不能假称已完成神经语义检索。
3. `atlas_pro.events`：持久事件队列与原子去重、重大 P0 风险事件优先、交易所节假日与提前收盘检查。交易日历使用 `exchange_calendars`，是运行依赖之一。
4. `atlas_pro.models`：角色与模型白名单、独立金融任务认证状态、到期失效、UTC 成本预算、同一请求幂等和并发资金预留。模型能力认证必须有外部评测的标识；标识本身仍需要部署环境中可信的评测签名/访问控制，不应把任意 JSON 当成有效证书。
5. `atlas_pro.risk`：仅研究建议使用的 fail-closed 检查器，验证投资政策、数据时间、账户完整性、税务及反方核查、仓位限制；无实际交易 API。**不是保证金模型或合规下单授权**。
6. `atlas_pro.licenses`：权限未知默认拒绝，明确隔离个人查询、持续索引、向量外传、模型训练与再分发。
7. `atlas_pro.feeds`：SEC CompanyFacts / Submissions、ALFRED 经济数据 vintage、BoC 数据的 HTTPS 端点及输入校验适配器；用 mock transport 测试。尚未连接真实 Key、限流队列、实际网络响应或官方配额。
8. `atlas_pro.release`：研究规则提升需要质量、风控、授权、Shadow Mode 证据和 HMAC 批准；可停止后续发布。签名密钥必须由模型进程外的操作员系统持有。
9. `atlas_pro.ibkr_bridge`：与现有 `personal_agent.finance` / `personal_agent.broker` 的只读接口对接。只认可已确认的 live broker capture；模拟回放、过期状态和对账失败一律限制为非实时。**真实 IBKR 连接尚未测试**。
10. `atlas_pro.__main__`：纯合成数据 smoke test，展示来源入库→检索→风控事件→假期判断→拒绝未授权交易，0 次网络、0 次付费 LLM、0 次真实订单。

## 2. 数据采购建议（个人使用）

| 优先 | 数据源 | 费用与性质 | 是否建议立即购买 | 授权注意事项 |
|---|---|---|---|---|
| P0 | SEC EDGAR | 政府公开文档、XBRL | 不需要购买 | 按 SEC User-Agent 与公平访问规则；`data.sec.gov` 公开 API 限流 |
| P0 | FRED / ALFRED | 免费 API Key | 不需要购买 | 使用 `realtime_start/realtime_end` 获取回测当时可知数据，检查第三方序列权利 |
| P0 | Bank of Canada Valet | 免费官方 API | 不需要购买 | 每日参考汇率≠实时可成交 FX 报价 |
| P0 | IBKR Flex + read-only TWS API | 既有个人账户；行情订阅可能额外收费 | 优先使用已有账户 | 多账户完整性、实时盘中 vs 账单差异、加拿大 API/市场权限 |
| P1 | Alpaca IEX 免费行情 | IEX 覆盖，不等于 SIP 全市场 NBBO | 可免费研究监控 | 不得将 IEX 中间价标成可成交全市场报价 |
| P1 | Tiingo EOD | Starter $0；Power $30/月 | 在历史价格量增加后再考虑 | 个人 Internal Use Only，不适用于对外发布 |
| P1 | Tiingo As-Reported Fundamentals | DJIA 30 免费基础；个人历史扩展 3/10/20+ 年每月 $9.99/$29.99/$49.99；确认与 Power 关系 | **最优先考虑的付费 PIT 基本面候选** | 部分数据为 third-party，须确认模型、向量索引及历史归档权利 |
| P2 | Massive | Financials $29/月；Stocks Advanced $199/月（页面查看时） | 暂不优先 | 个人套餐、实时报价覆盖、AI 使用和数据留存范围需确认 |
| P3 | Databento | 按流量及订阅计费 | 仅高频 / 订单簿策略需要时 | 交易所费用、个人/专业分类和微观数据规模 |
| 受限 | FMP | 免费和付费套餐 | 不作为训练集或永久数据库基座 | 2026-11 条款允许有条件个人 AI/RAG 分析，但明确禁止模型训练/微调/评测/校准/改进；限制替代性存档、redistribution |

**当前最值得付费的增量是合规的 PIT 基本面，而不是高速盘口。** 对长期投资系统，研究分析的财务数据正确性和可回放性通常比每秒行情细节更重要。没有获得原始供应商完整数据授权前，不能声称具备机构级、无偏全市场历史回测能力。

## 3. 知识库的实际状态与推荐升级

- **目前可运行**：本地 SQLite + FTS5、可选调用者提供的向量 callback、RRF 融合（当前仅示范接口），文档 SHA-256、来源 URL、日期、scope 检查。
- **下一步**：本地运行 `Qwen/Qwen3-Embedding-0.6B`，模型卡 Apache-2.0，官方 0.6B、最多 1024 维；个人 PC 可视硬件负载选择量化模型或 CPU。不应未经测试直接换成 4B/8B。
- **增长阶段**：达到 5万至几十万条引用片段、响应时间变差时再部署 Qdrant Local/Server，在 payload filter 里严格实现 `available_at <= decision_at`，`source_license` 与 `data_scope`。
- **必须保留**：来源检索不等于可信结论；SEC 原文、新闻与提示词都视为不可信数据，不能下达操作命令。LLM 输出只能包含 `source_id` 已验证的事实陈述。
- **必须隔离**：财务源数据与训练/评测样本库。FMP 等受限数据不能进入 Skill 评测/强化学习库；重新训练的训练数据需要单独许可与出处。
- **检索评测**：构建 100–300 道标注问题，测 `Recall@5`、`nDCG@10`、PIT 违规率、来源引用正确率和重要数字核对率。与纯 FTS5 基线比较；证明改善后再使用向量/重排。

## 4. 50 Agent 何时调用（运行规范）

- 日常事件路由基于已注册 21 类事件，避免每条行情变化启动大量模型。
- **P0**：保证金/账户/市场数据权限/未授权政策变更。只调用确定性风险岗位，禁止成本预算和冷却条件阻断。
- **P1**：重大披露及投资论点失效。先核实源文件和披露时点，再召集 Fundamental + Red Team。
- **P2**：业绩、估值买点、异常价格变化。按需求 5–18 个 Agent；价格触发仅开始研究，不自动买入。
- **P3**：每日组合、研究报告，批处理。新闻去重优先于模型推理。
- **P4**：每周预测复盘、每月策略实验和模型校准，所有策略改动先 Shadow Mode 后提请操作员批准。
- 全部 Agent 的实时订单权限均为 False。模型能力和数据/交易权限是两个独立维度。

## 5. 分级模型策略与成本

- `Python/Rules`：账户、税务核对、数值计算、时间戳、风控等确定性任务，约 19 个岗位默认不需云 LLM。
- `GPT-6 Luna / DeepSeek Flash / Claude Haiku`：普通分类、提取及轻量报告，按真实金融评测和费率选最便宜通过者。
- `Gemini Flash`：长文与多模态文献分析，注意到 2027-01-01 的官方价格变化。
- `GPT-6.2 Sol`：复杂财报论证、概率情景与投委会综合决策；不必每轮都 High effort。
- `Claude Sonnet`：供应商独立反方验证，降低同一家模型的共因偏差；不是统计上真正独立的证据。
- `GPT-6.2 Astra`：需要明确经济价值、相关风险、预算批准才升级；不设常驻角色。
- **实测门槛缺口**：真实金融评测没有运行，因此上述仍是待认证的初始路由，不是财务准确率排名。
- **预算审计**：新增并发请求的原子成本预留、到期认证阻断和本地模型计算成本的显式配置。当前成本仍为 token 估算，正式运行要读取供应商实际 usage settlement。

## 6. 与现有仓库的实际接口

复查截至 2026-11-21 提交 `c62f1147` 的代码：

- `personal_agent.finance.load_full_portfolio_snapshot()` 生成完整 PortfolioSnapshot。
- `personal_agent.finance.decision_snapshot()` 使用 broker enrichment，但原账本依旧为权威来源。
- `personal_agent.broker.latest_broker_snapshot()` 可能包含 `live_verified`, `capture_status`, `adapter`。
- `personal_agent.broker.reconcile_live_to_flex()` 可能返回 `reconciled` 或持仓/时间差异。
- 本次 `IBKRReadOnlyBridge` 只读取以上函数；只有状态正确才返回 `READ_ONLY_READY`，并且 `can_place_order=false`。

**没有同步真实账户、没有运行整个原仓库集成测试、没有提交 GitHub PR。** 当前用户无需提供账户 ID、Token 或密钥才能运行离线测试。正式集成时应先创建 feature branch，然后测试两个账户、保证金账户和 TFSA 的边界；不得把「能调用桥接函数」当作「已完成实盘级验证」。

## 7. 运行与复验

进入解压后的 `Atlas Investment OS Professional Upgrade` 目录：

```bash
# 本地研究核心（没有网络请求和交易权限）
python -m pip install -e .

# 启用交易所交易日历（必须安装才能测试 market_status）
python -m pip install -e ".[market_calendar]"

# 执行离线原型演示；自动创建并清理临时 SQLite 数据库
python -m atlas_pro

# 单元与模拟集成测试
python -m unittest discover -s tests -v

# 可选：测试覆盖率
python -m pip install coverage
coverage run --source=atlas_pro -m unittest discover -s tests
coverage run -a -m atlas_pro
coverage report -m
```

本运行环境内：119/119 通过；新增库加 CLI 演示覆盖率为 95%（语句覆盖率）。数字属于此独立包；真实 API、实盘成交、策略 Alpha 尚未通过验证。

## 8. 尚不能关闭的生产验收 Gate（必须如实保留）

| Gate | 当前真实状态 | 关闭条件 |
|---|---|---|
| G0 路由/数据许可/基础防护 | 本次独立原型通过 | 基于原仓库本地集成测试进一步复核 |
| G1 实时行情与持仓 | 未验收 | 用户授权下的真实 IBKR 双账户、行情权限、时延及断线测评 |
| G2 数据回测完整性 | 未验收 | 正式 PIT 数据集、退市和企业行动、货币、历史组合成分及成本校正 |
| G3 RAG 准确率 | 部分实现 | 本地 Embedding/Qdrant 部署及 100+ 标注检索任务 |
| G4 模型质量/成本 | 未验收 | 至少 100 项/金融研究类别的冻结案例、统计置信区间和实付费用 |
| G5 策略真实性 | 未验收 | 跨市场环境多窗口滚动样本外，含风险、成本、备选基准 |
| G6 执行安全 | 未验收 | 真实券商授权、风控网关、订单幂等、断线恢复、HITL 以及至少数周 Paper/Shadow |
| G7 生产监控 | 未验收 | 密钥库、备份恢复、告警升级、事故演练、权限审计、人工紧急停机 |

任何未验收 Gate 都不得被模型或 Agent 自行标记为已完成。真实交易必须保持禁用，直至用户另行明确授权且通过相关监管与券商规则核验。

## 9. 本轮复核的参考链接

- SEC EDGAR: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC fair access: https://www.sec.gov/about/developer-resources
- ALFRED vintages: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- Bank of Canada Valet: https://www.bankofcanada.ca/valet/docs
- IBKR market data: https://www.interactivebrokers.com/en/pricing/market-data-pricing.php
- IBKR Canada API limitation: https://www.interactivebrokers.com/support/faq/content/use-api-canada-73525898
- Alpaca free IEX scope: https://docs.alpaca.markets/us/docs/market-data-faq
- Tiingo individual pricing: https://www.tiingo.com/pricing
- Tiingo point-in-time fundamentals & add-on pricing: https://www.tiingo.com/products/fundamental-data-api
- Massive individual pricing: https://massive.com/pricing?product=stocks
- Databento pricing: https://databento.com/pricing
- FMP personal AI use and restrictions: https://site.financialmodelingprep.com/terms-of-service
- Qwen3 Embedding 0.6B: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- Qdrant hybrid RRF: https://qdrant.tech/documentation/hybrid-queries/
