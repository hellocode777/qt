# QP (Quant Platform) vs QuantTrading — 全面对比（v2）

> 对比日期：2026-08-11（v1 于 2026-07-20，3 周后重新对比）
> 说明：3 周内 QP 完成 Phase 0-6 全部落地（代码量 4 倍增长、测试 13 倍、补齐 Web UI/基本面/资金流），差距大幅缩小，结论已变化。

## 一、项目定位

| 维度 | QP (`~/workspace/qt`) | QuantTrading (`~/workspace/QuantTrading`) |
|------|-----------|-------------|
| **定位** | 量化研究+投资决策操作系统 | A股量化交易研究与信号生成系统 |
| **版本/阶段** | 10 层全实现（Phase 0-6 完成，进入生产冻结期） | 成熟期（已声明"可接入实盘"） |
| **Python** | 3.12+, `uv` + `hatchling` | 3.14, pip + requirements.txt |
| **Git 历史** | 153 commits（活跃迭代） | 42 commits（~1年活跃开发，最近仍提交） |
| **代码量** | 359 文件 / ~77,000 行（`qp/` 包） | 117 文件 / ~28,700 行 |
| **包管理** | `uv` + `pyproject.toml` | `pip` + `requirements.txt` |
| **测试** | **1488 测试函数**（全绿） | 14 个测试文件（集中在数据层） |

**定位差异**：QP 已从"架构先行"的平台骨架成长为**全功能量化操作系统**（研究→验证→策略→模拟→决策→监控→知识全链路）；QuantTrading 仍是**实战驱动**的工具型系统，专注信号生成与实盘贴近度。

---

## 二、架构设计哲学

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **层级数** | 10 层严格分层（全实现） | 松散分层（scripts → pipeline → strategy → data） |
| **层级隔离** | 严格禁止跨层依赖，不可向上引用 | 模块间直接调用，无强制边界 |
| **设计文档** | 28 条宪法 + 31 ADR + 10 TDR + 10 DP + 自查表 | 3 个核心文档（README + DESIGN + USAGE_GUIDE） |
| **领域术语** | 完整 Ubiquitous Language 规范 | 中文术语，无统一术语表 |
| **配置管理** | 4 级优先级（CLI > env > TOML > 默认），启动后冻结 | 单一 `config/__init__.py` + dataclass |
| **模块规范** | 严禁 `utils/`/`helpers/`/`common/`（审计 0 违规） | 有 `utils/`、`scripts/` 目录 |
| **Pipeline 模式** | 一切皆 Pipeline，`BasePipeline.run(context)` | `DailyPipeline` 链式调用（Step Builder） |
| **治理机制** | ADR-031 策略冻结快照、只跑 APPROVED、审计驱动 | 无形式化治理 |

**核心差异**：QP 是"宪法治理的平台"——每个决策有 ADR 可查、每个策略有生命周期状态机、每次变更有质量门禁；QuantTrading 是"不断扩建的车库工作室"——功能全面但缺少强制边界。

---

## 三、数据层对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **数据源** | AKShare + Tencent + Sina + Demo + **QuantTrading DB 适配器**（5 通道） | Tencent(主) + Sina + AKShare，4 级回退链 |
| **存储** | DuckDB + SQLite + Parquet（StorageFactory 抽象） | SQLite（WAL 模式） |
| **数据分层** | Raw → Bronze → Silver → Gold 四级 + PIT 双时间戳 | Raw price + Adj factors 双轨 |
| **复权处理** | CorporateAction 引擎（分红、拆股、配股） | 复权因子表 + compat 兼容层 |
| **数据清洗** | 4 阶段 ETL（异常→成交量→停牌→复权） | 4 阶段 ETL，619 行 |
| **基本面数据** | ✅ 新增 `data/fundamental/`（adapter + product） | ✅ ROE、毛利率、负债率等 |
| **估值数据** | ⚠️ 计划中 | ✅ PE_TTM、PB、PS_TTM、股息率 |
| **行业分类** | Shenwan 行业映射 | AKShare 行业分类 + 前缀回退 |
| **资金流向** | ✅ 新增 `data/capital_flow/`（adapter + product） | ✅ 北向资金、主力净流入 |
| **生存偏差** | 未显式处理 | ✅ 退市股票标记（delisted_handler） |
| **数据合约** | ✅ Data Contract 定义列 schema + Pandera 校验 | 无显式合约 |

**胜出方**：**基本打平**。QP 补齐了基本面/资金流两大维度（v1 时完全缺失），并拥有更严谨的 PIT 时间戳、Data Contract、Pandera Schema 校验；QuantTrading 仍有估值数据、生存偏差处理、更成熟的复权细节优势。

---

## 四、策略层对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **策略数量** | 6 个注册（momentum_vol_full 已 APPROVED，其余 research） | 12 个注册策略 |
| **因子数量** | 16 原始因子 → **6 复合 Alpha 源**（factor_composite 相关性合并） | 16+ 因子（5 大类） |
| **因子处理** | rank 标准化 + 复合合并（降过拟合） | MAD 缩尾 → z-score/rank → Gram-Schmidt 正交化 → 行业中性化 |
| **截面中性化** | ⚠️ 部分（行业中性在组合层） | ✅ 行业中性化 + 市值中性化 |
| **因子注册** | FeatureRegistry + factor_composite | `@register_factor` 装饰器 |
| **策略注册** | StrategyRegistry + 生命周期状态机（APPROVED=3） | `@register_strategy` 装饰器 + 统一对比评估 |
| **市场环境检测** | regime（市场状态检测模块） | MA50/MA200 + 波动率 + 宽度 + 成交量（6 态） |
| **状态自适应** | regime_ensemble（状态集成） | 仓位/换仓频率随市场状态自适应 |
| **信号生成** | 多因子打分 + 信号生成器（signal generator） | 排序 + rank buffer（减少换手） |
| **质量过滤** | ✅ quality_filter | ✅ ROE/毛利率预筛选 |
| **市场过滤** | ✅ market_filter | ✅ MA20/MA60 双均线确认 |
| **追涨保护** | ⚠️ 无显式 anti-chase | ✅ anti-chase protection |
| **策略融合** | factor_layers（因子分层）+ regime_ensemble | 多策略对比评估 + self_optimizer（自优化） |

**胜出方**：**QP 迎头赶上，各有千秋**。QP 有 6 复合因子（抗过拟合设计）和严格的 ADR-031 冻结治理；QuantTrading 有 12 个实战策略、更成熟的截面处理流水线、anti-chase 等 A 股细节。

---

## 五、回测引擎对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **T+1 执行** | ✅ | ✅ |
| **涨跌停检测** | ✅ | ✅（主板 ±10%、科创/创业 ±20%） |
| **停牌检测** | ✅ | ✅ |
| **滑点模型** | 3 种（固定、波动率、sqrt 冲击） | 流动性调整滑点（0.1%-0.5%） |
| **费率** | 印花税 + 佣金 | 印花税(0.1%) + 佣金(0.025%) + 滑点(0.1%) |
| **闲置资金利息** | ⚠️ 无 | ✅ 年化 2% |
| **卖先买后** | ✅ | ✅ |
| **风控集成** | 组合层风险引擎（portfolio_risk_engine + risk_exit） | 内置止损/止盈/最大持仓天数 |
| **成本模型** | ✅ portfolio/cost_model.py（独立模块） | 内嵌回测 |

**胜出方**：各有千秋。QP 的组合层风控和成本模型更系统化；QuantTrading 的 A 股细节更贴合实盘（科创/创业板涨跌幅、闲置资金利息）。

---

## 六、机器学习能力

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **模型** | LightGBM（LambdaRank 研究路径 + 分类器） | LightGBM 分类器 |
| **标签构建** | 有（label 模块） | ✅ extreme-label（行业内 top/bottom 30%） |
| **训练方式** | walk-forward + 重训 Pipeline | 3 年滚动 walk-forward，25 天 gap |
| **交叉验证** | ✅ PurgedKFold（ADR-021 强制） | Walk-forward split |
| **特征重要性** | ⚠️ 部分 | ✅ SHAP + feature importance |
| **模型诊断** | ✅ validation/engine（16 项检查） | ✅ model_diagnostics（预测分布、校准） |
| **模型注册** | ✅ ModelRegistry（SHA256 哈希） | 文件缓存 |
| **模型衰减检测** | ✅ 滚动 IC < 训练 IC 的 30% + kill_switch | ❌ 无显式检测 |
| **实验追踪** | ✅ 46 个实验 JSON + lineage 图（今天落地） | 无 |

**胜出方**：**QP 胜**。QP 现在有 PurgedKFold（强制）、验证门禁（16 项检查）、模型衰减监控、实验追踪、lineage 全链路；QuantTrading 的优势收窄为 SHAP 特征重要性、校准分析等诊断细节。

---

## 七、监控与运维

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **Kill Switch** | ✅ 3 触发器（回撤、组合回撤、PSI） | ❌ 无 |
| **特征漂移** | ✅ PSI + KS + Wasserstein | ❌ 无 |
| **告警通道** | 终端 + 日志 + Telegram | 终端 + 钉钉 + 企微 + 邮件 + Markdown |
| **知识沉淀** | ✅ 275 个 md（research_debt/failure_analysis/决策审计） | ❌ 无 |
| **实验追踪** | ✅ lineage graph（今天落地 `qp lineage snapshot`） | ❌ 无 |
| **Web UI** | ✅ **新增** `qp/web/`（FastAPI + routers + templates） | ✅ Streamlit 14 页仪表盘 |
| **自动定时执行** | APScheduler + systemd 服务（Restart=always） | crontab 脚本 |
| **Paper Trading** | ✅ 修复后真实运行中（30 天窗口） | ⚠️ shadow 模拟 |
| **策略生命周期** | ✅ ADR-031 冻结（APPROVED 才生产） | 无形式化状态机 |

**胜出方**：**QP 全面胜出**。监控（Kill Switch/漂移/衰减）、知识沉淀、实验追踪、治理机制（ADR-031）、Paper Trading 全部就位；QuantTrading 仅剩多渠道告警（钉钉/企微）和 Streamlit 页面数量优势（QP 的 Web 已存在但功能仍在初期）。

---

## 八、测试对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **测试数量** | **1488 测试函数**（全绿） | 14 个测试文件 |
| **测试覆盖** | 全层覆盖（决策/监控/组合/策略/配置/管线/运行时/lineage） | 数据层为主（清洗/ETL/存储 Schema/迁移） |
| **测试空白** | 集成测试目录存在但偏薄 | 策略、回测、因子计算均无测试 |
| **质量门禁** | ruff 0 + pyright 0 + pytest 全绿（pre-commit） | 无形式化门禁 |

**胜出方**：**QP 完胜**（1488 vs 14 个文件，13 倍差距，且全层覆盖 + 质量门禁）。QuantTrading 的策略/回测/因子零测试仍是最大隐患。

---

## 九、文档对比

| 维度 | QP | QuantTrading |
|------|-----|-------------|
| **架构文档** | 28 条宪法 + 31 ADR + 10 TDR + 10 DP + 自查表 | DESIGN.md (~27KB) |
| **使用指南** | README + user_guide + developer_guide + api | README + USAGE_GUIDE.md (~32KB) |
| **设计规范** | 编码风格、命名规范、测试标准（CLAUDE.md） | 无 |
| **架构自审** | ✅ §9 自查表 + 3 并行审计工具化 | 无 |

**胜出方**：**QP 完胜**——宪法体系（今天还整理了精简版/完整版分置 + 历史路线图归档）。

---

## 十、综合总结

| | QP | QuantTrading |
||---|---|---|
| **定位** | 宪法治理的量化研究操作系统 | 实战交易信号工具 |
| **成熟度** | ~90%（Phase 0-6 完成，生产冻结期） | ~70%（已声明可接入实盘） |
| **最大优势** | 严格架构+全链路监控+1488测试+宪法治理+知识沉淀 | 12 个实战策略+截面处理流水线+A股细节+Streamlit |
| **最大短板** | 策略实盘验证仍在进行（Paper Trading 30 天窗口） | 零策略测试+无监控体系+无形式化治理 |
| **适合场景** | 长期研究底座+投资决策操作系统 | 日常交易辅助+信号生成 |
| **设计风格** | 架构先行（Architecture-First） | 实战驱动（Practice-Driven） |

---

## 十一、互补建议（v2 更新）

### QP → QuantTrading 值得借鉴的（新增）

- 截面因子处理流水线（MAD 缩尾 → 正交化 → 中性化）——QP 目前缺完整流水线
- 12 个策略的实战经验（self_optimizer 自优化、rank buffer 换手控制、anti-chase）
- 退市股票处理（生存偏差消除）
- 科创/创业板涨跌幅区分、闲置资金利息等 A 股细节
- Streamlit 页面数量与交互性（QP 的 Web 还在初期）
- SHAP 特征重要性 + 校准分析（QP 模型诊断偏规则化）

### QuantTrading → QP 值得借鉴的（新增）

- **Kill Switch + 漂移检测 + 模型衰减监控**（QuantTrading 完全缺失，最大风险）
- **1488 测试 + 质量门禁**（QuantTrading 策略/回测零测试，实盘风险极大）
- ADR-031 策略冻结治理（QuantTrading 无状态机，改策略无审计）
- 28 条宪法 + 文档体系（设计决策可追溯）
- PurgedKFold + Validation Gate（防过拟合）
- 知识沉淀体系（research_debt/failure_analysis）

### 两个项目的共同盲区（v2 更新）

- **都没有实盘对接**（QP 是决策支持系统人工执行；QuantTrading 声明"可接入实盘"但代码仍以研究为主）
- 都没有 Point-in-Time 财务数据（用最新 restated 数据回看历史 = 前视偏差）
- QP 估值数据待建；QuantTrading 无系统化因子评估框架（IC 分析有但未接监控）
- 两个项目已经开始**互相吸收**（QP 的 fundamental/capital_flow 适配器里有 `quant_trading_db_adapter` 直接读 QuantTrading 的数据库！）

---

## 附：v1 → v2 关键变化

| 维度 | 2026-07-20 (v1) | 2026-08-11 (v2) |
|------|-----------------|-----------------|
| QP 代码量 | 150 文件 / 18.5K 行 | 359 文件 / 77K 行（4.2x） |
| QP Git | 9 commits | 153 commits（17x） |
| QP 测试 | 109 | 1488（13.6x） |
| QP 策略 | 2（MultiFactor 未集成） | 6 注册 + momentum_vol_full APPROVED |
| QP 因子 | 4 | 16 原始 → 6 复合 Alpha 源 |
| QP 基本面 | ❌ 无 | ✅ fundamental/ 模块 |
| QP 资金流 | ❌ 无 | ✅ capital_flow/ 模块 |
| QP Web UI | ❌ 无 | ✅ qp/web/（FastAPI） |
| QP Lineage | ⚠️ 引擎存在未落地 | ✅ `qp lineage snapshot` 落盘 |
| QP Paper Trading | ❌ 无记录 | ✅ 修复 + 30 天真实运行中 |
| 结论 | QP ~30% vs QT ~70% | QP ~90% vs QT ~70%，**角色反转** |
