#!/usr/bin/env bash
# #14 因子健康判定规则修正的提交与推送（2026-09-19）。
# 前置：uvx ruff format --check . / uvx ruff check . / uv run pyright / 全量 pytest 全绿。
set -euo pipefail
cd "$HOME/workspace/qt"

echo "=== git status ==="
git status --short

echo "=== 1/3 monitoring: 判定规则 ==="
git add qp/monitoring/factor_health.py tests/unit/test_factor_health_significance_gate.py
git commit -q -F - <<'MSG'
fix(monitoring): 因子健康判定三处修正 + 显著性门禁（#14）

初始假设（decay 阈值落在噪声 1σ 内 → degraded 泛滥）经实测部分推翻：只加 1σ 门禁时
28 因子 stage 零变化（越线斜率通常 3σ+）。真正的缺陷是另外三处：

1. 计数语义 bug：_count_consecutive_degraded 把当前标量（60 日斜率 / 全历史 IC_IR）
   当逐日条件 → 条件一成立计数即等于序列长度（实测 2822/2822 天），
   「连续 30 天」保护形同虚设 → 改为按 trailing 30 日均值序列计数（实测降到 0–43）
2. 方向语义 bug（最实质）：衰减用带符号 IC 计算 → 40% 的 direction=-1 因子
   「IC 更负 = 信号增强」被判成衰减（Implied_Net_Flow ic_30d=-0.059 强于 ic_90d=-0.016，
   斜率 -0.00267 → 旧逻辑判 DEGRADED）→ 衰减统一按 |IC| 计算
3. 口径改进：显著衰减时加中期对照 —— 90 日 IC 仍显著（|t| ≥ 2）判 WEAKENING
   （观察 + 降权 25%），否则 DEGRADED（降权 50%）
4. 保留 1σ 显著性门禁（threshold = decay_slope - σ·SE，可用 use_significance_gate 关闭），
   与策略级 rolling_ic 的 P1-3 口径对齐

实测（真实日 IC 序列，28 因子）：degraded 14→16、weakening 11→7、validated 3→5。
回归测试 10 项：tests/unit/test_factor_health_significance_gate.py
MSG

echo "=== 2/3 cli: validate 方向口径 ==="
git add qp/platform/cli/commands/factor_cmd.py
git commit -q -F - <<'MSG'
fix(cli): qp factor validate 的 IC>0% 改为方向调整后的同向占比（#14）

direction=-1 的因子 IC 天然为负，「IC>0% ≥ 50%」对它们结构性不适（必然失败）：
Amplitude_5D 31.3% / Momentum_3M 37.2% / Volume_Concentration 24.7% / Volume_Trend_10D 36.6%
→ 4 个反向因子永远 4/5。

改为按 expected_direction 换算的「同向占比 ≥ 50%」；实测 Amplitude_5D 同向 68.7%，
4/5 → 5/5（IC>0% 原值仍打印，保留信息）。
MSG

echo "=== 3/3 docs ==="
git add docs/tracking/qt_backlog_tracker.md scripts/research/factor_health_significance_gate_compare_20260919.py \
        scripts/maintenance/commit_20260919_factor_health_rules.sh
git commit -q -F - <<'MSG'
docs(factor): #14 判定规则修正留痕 + 改前/改后对照脚本

- tracker §#14 重写：如实记录被实测推翻的初始假设、两处真 bug、口径改进与实测效果
- scripts/research/factor_health_significance_gate_compare_20260919.py：
  用真实日 IC 序列对 legacy/new 两套规则做 stage 计数与逐因子差异对照
- 已知局限入档：衰减只看 trailing 60 日窗口 → 对台阶式下跌不敏感
MSG

echo "=== push ==="
for i in 1 2 3; do
  if git push origin master; then echo pushed; break; fi
  echo "push retry $i..."; sleep 5
done

echo "=== git log ==="
git log --oneline -4
git status --short
