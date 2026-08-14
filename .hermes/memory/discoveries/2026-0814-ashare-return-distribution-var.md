Task ID:        QT-2026-0814-001
Type:           Investigate
Goal:           A股日收益分布特征 vs GBM 假设，以及组合 VaR 应该用什么方法算
Scope:          portfolio risk layer / simulation research
Status:         DONE

Files inspected:
  - scripts/research/gbm_tail_comparison.py — 新建：真实 vs GBM 分布对比
  - scripts/research/bootstrap_var_compare.py — 新建：三模型 VaR 对比
  - data/dataset/daily_price_latest.parquet — 3051 只主板，2015-2026，7.2M 日收益

Evidence:
  - FACT: 真实日收益峰度 3.60（正态=0）、偏度 0.275；|ret|≥9.5% 占 3.29%（GBM 假设下≈0）
  - FACT: 单日 1% VaR 真实=9.98%（bootstrap CI 9.95-10.00%），GBM=7.45% → GBM 低估 1.34x
  - FACT: 单日 5% VaR 真实=4.76% < GBM=5.25% → 跌停截断压扁中间尾部，GBM 反而高估
  - FACT: 20 日路径 1% VaR 三模型均 28.4-28.6%（差异 1.00x，中心极限摊平）
  - FACT: 真实最大单日跌幅 -21% < GBM 模拟 -25.6%（涨跌停封顶）
  - FACT: A股随机 8 只组合 3-6/8 只股票 VaR 贡献 >15%（最大 32-47%）
  - FACT: 银行 8 只组合 VaR/平均单股VaR 比值 0.882（伪分散）；随机 8 只 0.60-0.67

Conclusion:
  A股尾部不是单纯肥尾，是"截断 + 聚集"：
  1. 风险集中在跌停事件（1% VaR ≈ 跌停线），不是连续正态尾部
  2. GBM 误差方向分周期：日频风控按 GBM 偏乐观（低估 34%）；长周期组合 VaR 用 GBM 够用
  3. 组合 VaR 必须用按交易日横截面重采样（bootstrap）——保留相关性，旧 sqrt-sum-of-squares
     假设独立会系统性低估 55-73%
  4. 组合分散化有效性可用"组合VaR/平均单股VaR"衡量：>0.75 视为伪分散

Confidence:     HIGH（7.2M 样本，真实数据验证）
Changes:        scripts/research/gbm_tail_comparison.py, bootstrap_var_compare.py（新增）
Tests:          N/A（研究脚本，手工运行验证）
Follow-up:
  - VaR overlay 已接入 portfolio_risk_engine（见 QT-2026-0814-003）
