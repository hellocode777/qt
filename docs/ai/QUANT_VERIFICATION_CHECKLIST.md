# Quant-Specific Verification Checklist（量化专项验证清单）

> 涉及量化逻辑（因子/IC/回测/策略/数据流水线/实验）的**任何修改或结论**，在交付前逐项自检。
> 这是普通 coding agent 没有的一层——QT 必须有。
> 原则：先验证再下结论；怀疑哪项不适用就写明「不适用 + 原因」，不要静默跳过。

## 11 项强制检查

- [ ] **Look-ahead bias（前视偏差）** — 计算只用 t 时刻及之前的信息；`shift(1)` 是否到位；因子值是否用了当日收盘后才有的数据
- [ ] **Future data leakage（未来数据泄漏）** — 训练/验证/回测窗口是否泄漏未来标签；`_load_prices` 补跑历史是否用了最新价 mark-to-market
- [ ] **Universe leakage（股票池泄漏）** — 股票池是否含未来才上市/退市的股票；filter 条件是否用到未来信息
- [ ] **Survivorship bias（幸存者偏差）** — 结论是否只基于今天还存活的股票；退市/停牌股是否被剔除导致收益虚高
- [ ] **Factor direction（因子方向）** — 改动是否悄悄改变因子符号/权重语义；方向=-1 的因子（A 股动量/量价天然负 IC）IC 为负是正常还是失效；是否查过 `qp/research/feature/*.py` 的 raw 定义
- [ ] **Rebalance timing（调仓时点）** — 调仓日判定、信号生成日与执行日的对齐；`is_rebalance_day` 语义
- [ ] **Transaction assumptions（交易假设）** — 手续费/印花税/滑点/涨跌停成交假设是否合理且与成本模型一致
- [ ] **Missing data（缺失值）** — 停牌/无数据日的处理方式（前向填充/剔除/NaN 传播）；是否被 `keep="last"` 之类合并策略掩盖
- [ ] **Corporate action（公司行为）** — 除权除息/拆股是否复权；价格跳变是真实行情还是未复权
- [ ] **Date alignment（日期对齐）** — trade_date 是 Date 还是 str；join 前是否统一 dtype；时区（Asia/Shanghai vs UTC）是否错位
- [ ] **Train/test contamination（训练/测试污染）** — PurgedKFold 的 purge/embargo 是否生效；超参搜索窗口与验证窗口是否重叠；「短样本最优参数」是否被写死进生产

## 已知项目语义（2026-08 实测，直接引用）

- 因子方向：`momentum.py:235-237`、`volume.py:147-156` 明言负 IC → direction=-1；**看 IC 前先查 direction**
- 生产读冻结快照：ADR-031 — APPROVED 策略读 `registry.get_approved()`，不读 `get_meta()`
- 数据流：Raw 不可变只追加；Gold 在 `data/dataset/*.parquet`
- 诊断工具：`qp/research/evaluation/quintile_diag.py`（分层诊断）；`scripts/audit_layers.py`（架构审计）

## 使用时机

| 场景 | 要求 |
|---|---|
| 改因子/策略/回测代码 | 逐项自检，报告中列出每项结论 |
| 解释因子 DEGRADED / IC 异常 | 至少过 direction / date alignment / missing data 三项 |
| 实验结论要进生产 | 全 11 项 + walk-forward/OOS 验证（用户量化素养要求） |
| 纯 WebUI/文档改动 | 声明「不涉及量化逻辑」，跳过清单 |

## 输出格式

在最终回复中给出：

```text
Quant Verification: 11/11 passed
- look-ahead: PASS (shift(1) verified at ...)
- factor direction: PASS (direction=-1, negative IC is expected)
- ...
- train/test contamination: N/A (no training involved)
```
