#!/usr/bin/env bash
# 2026-09-19 巡检四项修复的提交与推送。
# 前置：uvx ruff format --check . / uvx ruff check . / uv run pyright / 全量 pytest 全绿。
set -euo pipefail
cd "$(dirname "$0")/.." 2>/dev/null || cd "$HOME/workspace/qt"
cd "$HOME/workspace/qt"

echo "=== git status before ==="
git status --short

echo "=== 1/5 data: 指数新鲜度 ==="
git add qp/data/dataset/index_provider.py qp/platform/cli/commands/data_cmd.py \
        qp/pipeline/multifactor_pipeline.py tests/unit/data/test_index_provider.py
git commit -q -F - <<'MSG'
fix(data): 指数数据不再静默过时 — 新鲜度判定 + 消费侧刷新

- fetch_index_data(): 本地文件仅在最新 trade_date <= 7 天时复用；过时自动重抓；
  重抓失败 raise（错误消息含旧数据日期），不覆盖旧文件、不假装成功
- 新增 latest_local_date()；qp data index 打印最新交易日 + 两个指数文件 OK/STALE，支持 --symbol=
- multifactor_pipeline._load_index_data(): 过时先刷新，刷新失败回退旧数据 + WARNING（带滞后天数）
- 根因：旧逻辑「文件存在即 return」使 index_csi300 停在 2026-08-20（缺 20 个交易日），
  而策略侧 market filter / regime 一直在消费它
- 实测补拉：index_csi300 / index_sh000001 → 2026-09-18
MSG

echo "=== 2/5 monitoring: PSI 不可测显示 ==="
git add qp/platform/cli/commands/monitor.py qp/monitoring/kill_switch_pipeline.py \
        qp/web/templates/components/strategy_health.html
git commit -q -F - <<'MSG'
fix(monitoring): PSI / rolling IC 不可测时不再显示 0.000

- psi_available=False 时 report.psi_value 保持默认 0.0，四处曾无条件打印 →
  绿色 0.000 被读作「无漂移」，真相是「没测」（违反默认值不得伪装成测量值）
- qp monitor check / kill_switch 归档邮件摘要 按 psi_available 分支显示「不可测」
- strategy_health.html：PSI 与 rolling IC 均按 *_available 分支
- 与 P2-3（DecayStage.NOT_MEASURED）同一铁律
MSG

echo "=== 3/5 monitoring: retrain 信号 ==="
git add qp/monitoring/retrain_signal.py qp/platform/cli/commands/scheduler.py \
        tests/unit/test_monitoring.py tests/unit/test_retrain_signal_weights.py \
        tests/e2e/test_daily_workflow.py scripts/maintenance/
git commit -q -F - <<'MSG'
fix(monitoring): retrain 信号的日期窗口/重复告警/假 PSI 降权

- load_history(days, limit=None) 由 head(days*10)（行数上限冒充日期窗口）改为按
  date >= today - days 过滤；告警里的「70 actionable」正是该上限
- retrain_notify 只对上次通知之后的新信号发信（状态 data/monitoring/retrain_notify_state.json），
  无新信号只打日志，不再每天重复同一批
- load_weight_scales 防御：trigger=PSI_DRIFT 且 psi_value >= 1.0（阈值体系 0.10/0.25）→ 跳过 + WARNING
- 数据修正：scripts/maintenance/purge_implausible_psi_signals_20260919.py
  （备份 retrain_signals_archive_20260919.parquet，移除 66 行假 PSI，198 → 132 行）
  pre-P2-2 的假 PSI 曾把 momentum_vol_full 降权至 0.85（9/2–9/11）；现 load_weight_scales → 1.0
MSG

echo "=== 4/5 portfolio: ADV 单位 ==="
git add qp/portfolio/cost_model.py qp/portfolio/exposure/liquidity_exposure.py \
        qp/portfolio/portfolio_risk_engine.py qp/shared/constants/__init__.py \
        tests/unit/test_portfolio.py
git commit -q -F - <<'MSG'
fix(portfolio): ADV 计算补 手→股 换算（volume 单位是手）

- 日线 volume 单位是「手」（1 手 = 100 股）：成交额 = close × volume × SHARES_PER_LOT
- 单一来源 qp/shared/constants.SHARES_PER_LOT；三处同源实现统一修正：
  cost_model.MarketImpactModel.compute_adv / liquidity_exposure._compute_adv /
  portfolio_risk_engine._compute_advs
- 漏系数后果：ADV 低估 100× → 冲击成本高估 10×、10%-ADV 流动性惩罚提前 100× 触发、
  liquidity_score 被系统性压低 0.2（影响 daily_pipeline Step 11 estimated_cost_pct）
- 证据：600519 @2026-09-18 close=1257.12 volume=24891 → 按手 ¥31.3 亿（合理）、按股 ¥3,129 万
MSG

echo "=== 5/5 docs ==="
git add docs/tracking/qt_backlog_tracker.md docs/ai/COMMAND_MAP.md docs/ai/PROJECT_MAP.md
git commit -q -F - <<'MSG'
docs: 巡检四项修复留痕 + 同步 AI 导航层

- docs/tracking/qt_backlog_tracker.md 新增 §#13-1~4（现象/根因/修复/验证，带 checkbox）
- docs/ai/COMMAND_MAP.md：data index 子命令、PSI/IC 显示铁律、retrain_notify 去重与信号→权重链
- docs/ai/PROJECT_MAP.md：data/monitoring 产物、scripts/ 目录
MSG

echo "=== push ==="
for i in 1 2 3; do
  if git push origin master; then echo "pushed"; break; fi
  echo "push retry $i..."; sleep 5
done

echo "=== git log ==="
git log --oneline -6
git status --short
