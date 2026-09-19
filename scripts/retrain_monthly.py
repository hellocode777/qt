#!/usr/bin/env python3
"""月度重训：验证当前策略 + 优化新权重 + 生成候选快照。

编排 qp 官方命令（不绕路）：
  1. 读当前 APPROVED 冻结权重（registry）
  2. 跑验证实验：qp experiment run multifactor --freeze-weights <当前权重>
     → 当前策略在最近窗口的 OOS 表现
  3. 跑优化实验：qp experiment run multifactor --optimize-weights
     → IC 驱动的新权重候选（multifactor_pipeline._optimize_weights_from_ic）
  4. 解析最新两个实验 JSON，对比，生成候选快照
     data/retrain_candidates/candidate_YYYYMMDD.json（gitignored 运行产物）

用法（qt 仓库根目录）:
  .venv/bin/python scripts/retrain_monthly.py
  .venv/bin/python scripts/retrain_monthly.py --strategy momentum_vol_full --lookback-months 12
  .venv/bin/python scripts/retrain_monthly.py --max-stocks 500   # 快速验证（小样本可能被 gate 拦截）
  .venv/bin/python scripts/retrain_monthly.py --skip-gate        # 仅探索：跳过质量门禁

输出：候选快照文件 + 摘要文本（stdout）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from qp.shared.json_io import json_load

ROOT = Path(__file__).resolve().parent.parent
QP = str(ROOT / ".venv" / "bin" / "qp")
CANDIDATE_DIR = ROOT / "data" / "retrain_candidates"
EXPERIMENTS_DIR = ROOT / "data" / "experiments"

# 当前生产策略（唯一 APPROVED）
DEFAULT_STRATEGY = "momentum_vol_full"


def _load_approved(strategy: str) -> dict:
    """读当前 APPROVED 冻结快照（ADR-031：approve 时冻结的 weights/parameters）。"""
    sys.path.insert(0, str(ROOT))
    from qp.strategy.registry import StrategyRegistry

    registry = StrategyRegistry()
    approved = registry.get_approved(strategy)
    if approved is not None:
        bs = getattr(approved, "backtest_summary", {}) or {}
        return {
            "weights": dict(getattr(approved, "weights", {})),
            "parameters": dict(getattr(approved, "parameters", {})),
            "backtest_ic": bs.get("ic"),
            "backtest_sharpe": bs.get("sharpe"),
        }
    meta = registry.get_meta(strategy)
    return {
        "weights": dict(meta.weights or {}),
        "parameters": dict(meta.parameters or {}),
        "backtest_ic": meta.backtest_ic,
        "backtest_sharpe": meta.backtest_sharpe,
    }


def _latest_trade_date() -> str:
    """最近交易日 = daily_price_latest.parquet 的最大 trade_date。"""
    path = ROOT / "data" / "dataset" / "daily_price_latest.parquet"
    if not path.exists():
        return datetime.now().strftime("%Y-%m-%d")
    df = pl.read_parquet(str(path))
    if "trade_date" not in df.columns or df.is_empty():
        return datetime.now().strftime("%Y-%m-%d")
    return str(df["trade_date"].max())


def _run_experiment(strategy: str, start: str, end: str, extra: list[str]) -> dict:
    """跑一个 qp experiment run multifactor，返回实验 JSON 摘要。

    extra 示例：["--freeze-weights", "{\"...\": 0.1}"] 或 ["--optimize-weights"]
    """
    cmd = [
        QP,
        "experiment",
        "run",
        "multifactor",
        "--strategy",
        strategy,
        "--start",
        start,
        "--end",
        end,
        *extra,
    ]
    print(f"  ▶ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=3600)  # noqa: S603 — cmd 由脚本内部构造，无外部输入
    if proc.returncode != 0:
        # 非零退出（如 gate 拦截/归档）不视为脚本失败——记录 stderr 摘要
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        print(f"  ⚠ 实验进程退出码 {proc.returncode}；尾部输出:\n{tail}", flush=True)

    # 找到刚生成的最新实验 JSON
    files = sorted(EXPERIMENTS_DIR.glob("multifactor_*.json"), key=os.path.getmtime)
    if not files:
        return {"error": "no experiment json produced"}
    latest = files[-1]
    data = json_load(latest)
    metrics = data.get("metrics", {})
    return {
        "experiment_id": data.get("experiment_id", latest.stem),
        "file": str(latest),
        "weights": (data.get("config", {}) or {}).get("model_params", {}),
        "gate_result": data.get("gate_result"),
        "metrics": {
            "ic_mean": metrics.get("ic_mean"),
            "ic_ir": metrics.get("ic_ir"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "excess_return_pct": metrics.get("excess_return_pct"),
            "total_return_pct": metrics.get("total_return_pct"),
        },
    }


def _fmt(v, suffix="") -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):+.2f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY)
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--max-stocks", type=int, default=0, help="0=不限制（全市场）")
    parser.add_argument("--skip-gate", action="store_true", help="跳过质量门禁（仅探索）")
    args = parser.parse_args()

    strategy = args.strategy
    end = _latest_trade_date()
    start = (
        datetime.strptime(end, "%Y-%m-%d") - timedelta(days=30 * args.lookback_months)
    ).strftime("%Y-%m-%d")
    print(f"月度重训 [{strategy}]  窗口: {start} → {end}", flush=True)

    current = _load_approved(strategy)
    if not current["weights"]:
        print(f"❌ 策略 {strategy} 无已批准权重，无法重训", file=sys.stderr)
        return 1
    print(f"当前 APPROVED 权重: {current['weights']}", flush=True)

    base = ["--max-stocks", str(args.max_stocks)]
    if args.skip_gate:
        base.append("--skip-gate")

    # 1) 验证实验：冻结当前权重，看最近窗口表现
    print("\n[1/2] 验证实验（冻结当前权重）…", flush=True)
    exp_current = _run_experiment(
        strategy,
        start,
        end,
        [*base, "--freeze-weights", json.dumps(current["weights"])],
    )

    # 2) 优化实验：IC 驱动新权重
    print("\n[2/2] 优化实验（IC 加权新权重）…", flush=True)
    exp_optimized = _run_experiment(strategy, start, end, [*base, "--optimize-weights"])

    # ── 对比与裁决 ──
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    cand_id = f"retrain_{datetime.now().strftime('%Y%m%d')}"
    cand_path = CANDIDATE_DIR / f"{cand_id}.json"

    cur_ic = exp_current.get("metrics", {}).get("ic_mean")
    cur_sharpe = exp_current.get("metrics", {}).get("sharpe_ratio")
    opt_ic = exp_optimized.get("metrics", {}).get("ic_mean")
    opt_sharpe = exp_optimized.get("metrics", {}).get("sharpe_ratio")

    if cur_ic is None and opt_ic is None:
        verdict, message = (
            "FACTORS_FAILED",
            "两个实验均无有效结果（可能被质量门禁拦截）——因子整体失效信号，建议审查因子集",
        )
    elif opt_ic is not None and (cur_ic is None or opt_ic > cur_ic):
        verdict = "UPGRADE"
        message = (
            f"优化权重在最近 {args.lookback_months} 个月表现更优 "
            f"(IC {_fmt(opt_ic)} vs {_fmt(cur_ic)}；Sharpe {_fmt(opt_sharpe)} vs {_fmt(cur_sharpe)})"
        )
    elif cur_ic is not None and cur_ic <= 0.02:
        verdict = "DECAY"
        message = f"当前策略最近窗口 IC={cur_ic:.4f} 已低于 0.02 阈值，建议人工重训或考虑替换"
    else:
        verdict = "HOLD"
        message = (
            f"当前策略最近 {args.lookback_months} 个月表现健康 "
            f"(IC {_fmt(cur_ic)}，Sharpe {_fmt(cur_sharpe)})，无需切换"
        )

    snapshot = {
        "candidate_id": cand_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "strategy": strategy,
        "window": {"start": start, "end": end},
        "current": {
            "weights": current["weights"],
            "backtest_ic": current.get("backtest_ic"),
            "backtest_sharpe": current.get("backtest_sharpe"),
            "recent_metrics": exp_current.get("metrics", {}),
            "gate_result": exp_current.get("gate_result"),
        },
        "optimized": {
            "weights": exp_optimized.get("weights", {}),
            "metrics": exp_optimized.get("metrics", {}),
            "gate_result": exp_optimized.get("gate_result"),
        },
        "verdict": verdict,
        "message": message,
        "experiments": {
            "current": exp_current.get("experiment_id"),
            "optimized": exp_optimized.get("experiment_id"),
        },
    }
    cand_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 摘要输出 ──
    print("\n" + "=" * 72)
    print(f"裁决: {verdict}  —  {message}")
    print(f"候选快照: {cand_path}")
    print("\n指标对比:")
    print(f"  {'':28s} {'当前权重(冻结)':>14s} {'优化权重':>14s}")
    print(f"  {'IC_mean':28s} {_fmt(cur_ic):>14s} {_fmt(opt_ic):>14s}")
    print(f"  {'Sharpe':28s} {_fmt(cur_sharpe):>14s} {_fmt(opt_sharpe):>14s}")
    print(
        f"  {'Excess_ret%':28s} {_fmt(exp_current.get('metrics', {}).get('excess_return_pct')):>14s} "
        f"{_fmt(exp_optimized.get('metrics', {}).get('excess_return_pct')):>14s}"
    )
    if exp_optimized.get("weights"):
        print("\n优化权重（若 UPGRADE 可用 --freeze-weights 复核后 approve）:")
        for k, v in exp_optimized["weights"].items():
            print(f"    {k}: {v:+.4f}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
