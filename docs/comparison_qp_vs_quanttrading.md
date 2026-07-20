# QP (Quant Platform) vs QuantTrading — 全面对比

> 对比日期：2026-07-20

## 一、项目定位

| 维度 | QP (`qt/`) | QuantTrading |
|------|-----------|-------------|
| **定位** | 量化研究+投资决策操作系统 | A股量化交易研究与信号生成系统 |
| **版本** | `0.0.1` Pre-Alpha | 成熟期（已声明"可接入实盘"） |
| **Python** | 3.12+, `uv` + `hatchling` | 3.14, pip + requirements.txt |
| **Git 历史** | 9 commits（Phase 0 → Phase 6） | 40 commits（~1年活跃开发） |
| **代码量** | ~18,500 行 / 150 个 Python 文件 | ~28,700 行 / ~90 个 Python 文件 |
| **包管理** | `uv` + `pyproject.toml` | `pip` + `requirements.txt` |

**定位差异**：QP 是一个**架构先行、文档驱动**的平台型项目，强调严格的层级边界和设计原则；QuantTrading 是一个**实战驱动、快速迭代**的工具型项目，强调可用性和真实市场适配。

---

## 二、架构设计哲学

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **层级数** | 10层严格分层 | 松散分层（scripts → pipeline → strategy → data） |
| **层级隔离** | 严格禁止跨层依赖，不可向上引用 | 模块间直接调用，无强制边界 |
| **设计文档** | 30个ADR + 10个TDR + 28条宪法规则 | 3个核心文档（README + DESIGN + USAGE_GUIDE） |
| **领域术语** | 有完整的 Ubiquitous Language 规范 | 使用中文术语，无统一术语表 |
| **配置管理** | 4级优先级（CLI > 环境变量 > TOML > 默认），启动后冻结 | 单一 `config/__init__.py` + `StrategyConfig` dataclass |
| **模块规范** | 严禁 `utils/`、`helpers/`、`common/` | 有 `utils/`、`scripts/` 目录 |
| **Pipeline 模式** | 一切皆 Pipeline，`BasePipeline.run(context)` | `DailyPipeline` 6 步骤链式调用（Step Builder） |

**核心差异**：QP 的设计像一座按照蓝图精心建造的建筑，每一层都有明确的契约；QuantTrading 像一个不断扩建的车库工作室，功能齐全但边建边改。

---

## 三、数据层对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **数据源** | Tencent(主) + AKShare + Demo(合成) | Tencent(主) + Sina + AKShare，4级回退链 |
| **存储** | DuckDB + SQLite + Parquet（StorageFactory 抽象） | SQLite（WAL 模式） |
| **数据分层** | Raw → Bronze → Silver → Gold 四级 | Raw price + Adj factors 双轨 |
| **复权处理** | 通过 CorporateAction 引擎（分红、拆股、配股） | 复权因子表 + compat 兼容层 |
| **数据清洗** | 基础清洗（停牌、涨跌停） | 4阶段 ETL（异常→成交量→停牌→复权），619 行 |
| **基本面数据** | 无（计划中） | 有（ROE、毛利率、负债率等，带发布日期） |
| **估值数据** | 无 | 有（PE_TTM、PB、PS_TTM、股息率） |
| **行业分类** | Shenwan 行业映射 | AKShare 行业分类 + 前缀回退 |
| **资金流向** | 无 | 北向资金、主力净流入 |
| **生存偏差** | 未处理 | 已处理（退市股票标记） |
| **数据合约** | 有 Data Contract 定义列 schema | 无显式合约 |

**胜出方**：QuantTrading 的数据层成熟度远超 QP — 它有基本面、估值、行业、资金流向等 QP 完全缺失的数据维度，以及更完善的数据清洗和生存偏差处理。

---

## 四、策略层对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **策略数量** | 2 个（SimpleRank 主力，MultiFactor 未集成） | 10 个已注册策略 |
| **因子数量** | 4 个（动量、波动率、成交量、资金流） | 16+ 个（5 大类 + 估值因子） |
| **因子处理** | 仅基础计算 | 完整流水线：MAD 缩尾 → z-score/rank 标准化 → Gram-Schmidt 正交化 → 行业中性化 |
| **截面中性化** | ❌ 缺失 | ✅ 行业中性化 + 市值中性化 |
| **因子注册** | FeatureRegistry | `@register_factor` 装饰器 |
| **策略注册** | StrategyRegistry + 生命周期状态机 | `@register_strategy` 装饰器 + 统一对比评估 |
| **市场环境检测** | ADX（趋势/震荡/波动 3 态） | MA50/MA200 + 波动率 + 宽度 + 成交量（6 态） |
| **状态自适应** | 无 | 仓位/换仓频率随市场状态自适应 |
| **信号生成** | 简单 Top-N 排序 | 排序 + rank buffer（卖出区 = top_n × 2 减少换手） |
| **质量过滤** | ✅ QualityFilterStrategy | ✅ ROE/毛利率预筛选 |
| **市场过滤** | ✅ MarketFilterStrategy | ✅ MA20/MA60 双均线确认 |
| **追涨保护** | 无 | ✅ anti-chase protection |

**胜出方**：QuantTrading 的策略层远远领先 — 10 个策略、16+ 因子、截面处理、自适应机制，这些都是 QP 目前缺失的核心能力。

---

## 五、回测引擎对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **T+1 执行** | ✅ | ✅ |
| **涨跌停检测** | ✅ | ✅（主板 ±10%、科创/创业 ±20%） |
| **停牌检测** | ✅ | ✅ |
| **滑点模型** | 3 种（固定、波动率、sqrt 冲击） | 流动性调整滑点（0.1%-0.5%） |
| **费率** | 印花税 + 佣金 | 印花税(0.1%) + 佣金(0.025%) + 滑点(0.1%) |
| **闲置资金利息** | 无 | ✅ 年化 2% |
| **卖先买后** | ✅ | ✅ |
| **风控集成** | 事后检查（Kill Switch） | 内置止损/止盈/最大持仓天数 |

**胜出方**：各有千秋。QP 滑点模型更多样，QuantTrading A股细节更贴合实盘（闲置资金利息、科创/创业板涨跌幅区分）。

---

## 六、机器学习能力

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **模型** | LightGBM LambdaRank | LightGBM 分类器 |
| **标签构建** | 计划中（`label/` 为空） | ✅ extreme-label（行业内 top/bottom 30%） |
| **训练方式** | 月度重训 Pipeline | 3 年滚动 walk-forward，25 天 gap |
| **交叉验证** | ✅ PurgedKFold（完整实现，245 行） | Walk-forward split |
| **特征重要性** | ❌ 缺失 | ✅ SHAP + feature importance |
| **模型诊断** | ❌ 缺失 | ✅ 预测分布、校准分析 |
| **模型注册** | ✅ ModelRegistry（SHA256 哈希） | 文件缓存 |
| **模型衰减检测** | ✅ 滚动 IC < 训练 IC 的 30% | 无显式检测 |

**胜出方**：ML 训练流程 QuantTrading 更完整（有标签构建和模型诊断），QP 的 PurgedKFold 实现和模型衰减监控是亮点，但训练链路整体尚未打通。

---

## 七、监控与运维

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **Kill Switch** | ✅ 3 触发器（回撤、组合回撤、PSI） | ❌ 无 |
| **特征漂移** | ✅ PSI + KS + Wasserstein 距离 | ❌ 无 |
| **告警通道** | 终端 + 日志 + Telegram | 终端 + Markdown 文件 + 钉钉 + 企微 + 邮件 |
| **知识沉淀** | ✅ KnowledgeArchive（5 模板，全文搜索） | ❌ 无 |
| **实验追踪** | ✅ 血缘图（lineage graph） | ❌ 无 |
| **Web UI** | ❌ 无 | ✅ Streamlit 14 页仪表盘 |
| **自动定时执行** | APScheduler + systemd timer | crontab 脚本 |

**胜出方**：QP 在监控和风险控制的系统化方面胜出（Kill Switch、漂移检测、知识归档）；QuantTrading 在实用性上更强（Web UI、多渠道告警）。

---

## 八、测试对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **测试数量** | 109 个（全部通过） | 17 个测试文件 |
| **测试覆盖** | 决策、监控、组合、策略、配置、管线、运行时 | 数据清洗、ETL 阶段、存储 Schema、迁移 |
| **测试空白** | 集成测试/E2E 目录存在但为空 | 策略、回测、因子计算均无测试 |
| **测试框架** | pytest + pytest-cov | pytest + 3 自定义标记 |

**胜出方**：QP 测试覆盖更全面（跨层覆盖），QuantTrading 测试集中在数据层而策略/回测为零测试。

---

## 九、文档对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **架构文档** | 30 ADR + 10 TDR + 10 DP + 宪法 v4.2 | DESIGN.md (~27KB) |
| **使用指南** | README + progress.md | README + USAGE_GUIDE.md (~32KB) |
| **设计规范** | 编码风格、命名规范、测试标准 | 无 |
| **架构自审** | ✅ credibility_check.md（7 类审计） | 无 |

**胜出方**：QP 文档体系堪称教科书级别，每个设计决策都有据可查。QuantTrading 的文档注重实用性。

---

## 十、综合总结

| | QP | QuantTrading |
|---|---|---|
| **定位** | 架构蓝图型平台 | 实战交易工具 |
| **成熟度** | ~30%（Phase 6 / 长期规划 28 周） | ~70%（已声明可接入实盘） |
| **最大优势** | 严格架构、完善文档、监控体系、知识管理 | 策略丰富、数据全面、A股适配度高、Web UI |
| **最大短板** | 策略单薄、基本面数据缺失、无截面中性化、无 Web 界面 | 无系统化监控（漂移/衰减/Kill Switch）、无严格层级边界、测试覆盖不均 |
| **适合场景** | 作为长期研究的平台底座，适合持续迭代构建 | 作为日常交易辅助工具，适合策略研究和信号生成 |
| **设计风格** | 架构先行（Architecture-First） | 实战驱动（Practice-Driven） |

---

## 十一、互补建议

两个项目恰好形成互补：

### QP → QuantTrading 值得借鉴的

- Kill Switch + 漂移检测 + 模型衰减监控机制
- KnowledgeArchive 知识沉淀体系
- PurgedKFold 严谨的交叉验证实现
- 严格的层级边界和依赖管理
- 实验追踪与血缘图
- 配置冻结和 4 级优先级系统

### QuantTrading → QP 值得借鉴的

- 基本面/估值/行业/资金流向数据维度
- 横截面因子处理流水线（缩尾 → 标准化 → 正交化 → 行业中性化）
- 10 个策略的实战经验、16+ 因子库
- 10 种设计模式（装饰器注册、Config-as-Strategy、统一风控、兼容层、rank buffer 等）
- Streamlit Web 仪表盘
- 退市股票处理（生存偏差）
- 闲置资金利息、科创/创业板涨跌幅区分等 A 股细节
- 多渠道告警（钉钉、企微、邮件）

### 两个项目的共同盲区

- 都没有真正的集成测试/E2E 测试
- 都没有实盘对接（QP 明确是决策支持系统，人工执行；QuantTrading 虽声明"可接入实盘"但代码仍以研究为主）
- 都没有 Point-in-Time 财务数据（用最新 restated 数据回看历史 = 前视偏差）
- QP 完全缺乏基本面因子；QuantTrading 虽有基本面数据但缺乏系统化的因子评估框架
