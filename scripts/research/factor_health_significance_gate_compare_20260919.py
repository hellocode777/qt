"""因子健康判定规则的改前/改后对照（#14，2026-09-19）。

对比两种配置在真实日 IC 序列（data/monitoring/factor_ic_series.parquet，28 因子）上的判定差异：

  A. 改动前：标量 decay/IC_IR 当逐日条件（连续计数器实际等于全历史长度）+ 无显著性门禁
  B. 改动后：显著性门禁（σ=1）+ 连续计数按 trailing 30 日均值序列判定

输出 stage 计数变化与逐因子差异明细，供规则改动后的回归验证。
"""

from __future__ import annotations

import os

import numpy as np
import polars as pl

os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from qp.monitoring.factor_health import FactorHealthMonitor  # noqa: E402

SEVERITY = {
    "retired": 0,
    "degraded": 1,
    "weakening": 2,
    "research": 3,
    "validated": 4,
    "production": 5,
}


class LegacyMonitor(FactorHealthMonitor):
    """改动前行为（用于对照）：逐日条件里混用当前标量 decay / 全历史 IC_IR。"""

    def __init__(self) -> None:
        super().__init__(use_significance_gate=False)

    def _count_consecutive_degraded(
        self,
        valid: np.ndarray,
        decay_rate: float,
        ic_ir: float,
        decay_threshold: float | None = None,
    ) -> int:
        thr = self._decay_slope if decay_threshold is None else decay_threshold
        ic_ir_floor = 0.30
        count = 0
        for val in reversed(valid):
            if abs(val) < 0.02 or decay_rate < thr or ic_ir < ic_ir_floor:
                count += 1
            else:
                break
        return count


def main() -> None:
    df = pl.read_parquet("data/monitoring/factor_ic_series.parquet")
    factors = sorted(df["factor_name"].unique().to_list())

    legacy = LegacyMonitor()
    new = FactorHealthMonitor()

    before_counts: dict[str, int] = {}
    after_counts: dict[str, int] = {}
    changed: list[dict] = []

    for f in factors:
        ics = df.filter(pl.col("factor_name") == f)["ic"].drop_nulls().to_list()
        if len(ics) < 300:
            continue
        b = legacy.check_factor(f, ics)
        a = new.check_factor(f, ics)
        before_counts[b.lifecycle.value] = before_counts.get(b.lifecycle.value, 0) + 1
        after_counts[a.lifecycle.value] = after_counts.get(a.lifecycle.value, 0) + 1
        if b.lifecycle != a.lifecycle or b.consecutive_degraded_days != a.consecutive_degraded_days:
            changed.append(
                {
                    "factor": f,
                    "stage": f"{b.lifecycle.value} → {a.lifecycle.value}",
                    "consec_deg": f"{b.consecutive_degraded_days} → {a.consecutive_degraded_days}",
                    "ic_30d": round(a.ic_30d, 4),
                    "decay60": a.ic_decay_rate,
                    "ic_ir": a.ic_ir,
                }
            )

    print("=== stage 计数：改动前 vs 改动后 ===")
    keys = sorted(set(before_counts) | set(after_counts), key=lambda k: SEVERITY.get(k, 9))
    for k in keys:
        print(f"  {k:12s} {before_counts.get(k, 0):3d} → {after_counts.get(k, 0):3d}")
    print(f"\n=== 差异明细（{len(changed)} 个因子） ===")
    print(pl.DataFrame(changed).to_pandas().to_string(index=False) if changed else "  （无变化）")


if __name__ == "__main__":
    main()
