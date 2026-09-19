"""一次性数据修正：清除 retrain_signals.parquet 中不可信的 PSI 信号。

背景（证据链）：
  - P2-2（2026-09-11）确认修复前的 PSI 实现会在薄样本上产出假值
    （实测 15.529），docs/tracking/qt_backlog_tracker.md §#10 P2-2。
  - 这些行以 trigger=PSI_DRIFT / action=SCHEDULE_RETRAIN 落盘，并被
    daily_pipeline Step 9 的 load_weight_scales 消费 → 生产策略被降权 15%
    （momentum_vol_full 9/2–9/11），且把组合总敞口 scale 压到 0.85。
  - 判据：psi_value >= 1.0（阈值体系为 0.10 / 0.25，两者相差 1–2 个数量级；
    全表 66 行该类值域为 4.22–22.32，无一落在 (0.25, 1.0] 区间）。

动作：
  1. 全量备份到 data/monitoring/retrain_signals_archive_20260919.parquet
  2. 从主文件移除 trigger=PSI_DRIFT 且 psi_value >= 1.0 的行
  3. 打印前后行数与移除明细

幂等：重复执行不会进一步改动（移除条件已无匹配）。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

BASE = Path("data/monitoring")
MAIN = BASE / "retrain_signals.parquet"
ARCHIVE = BASE / "retrain_signals_archive_20260919.parquet"
MAX_CREDIBLE_PSI = 1.0

df = pl.read_parquet(MAIN)
print(f"before: {df.height} rows")

if not ARCHIVE.exists():
    df.write_parquet(ARCHIVE)
    print(f"archived full copy → {ARCHIVE}")
else:
    print(f"archive already exists → {ARCHIVE} (kept)")

bad = df.filter((pl.col("trigger") == "PSI_DRIFT") & (pl.col("psi_value") >= MAX_CREDIBLE_PSI))
print(f"removing {bad.height} implausible PSI rows:")
if bad.height:
    print(bad.group_by(["date", "strategy_name", "psi_value"]).len().sort("date").to_dicts()[:10])

clean = df.filter(~((pl.col("trigger") == "PSI_DRIFT") & (pl.col("psi_value") >= MAX_CREDIBLE_PSI)))
clean.write_parquet(MAIN)
print(f"after: {clean.height} rows")
print("remaining trigger/action:", clean.group_by(["trigger", "action"]).len().to_dicts())
