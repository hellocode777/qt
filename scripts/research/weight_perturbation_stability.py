"""权重扰动稳定性检验：选权重前先证明它不是噪声。

背景（2026-10-28 实测）：
  momentum_vol_full 的 v20260811 权重与 B 组重训权重各维度仅差 7–23%，但首日
  Top-10 有 5 只不同、同股票股数差 1.3–1.8 倍、净值日收益相关仅 0.874，
  总收益差 46pp（+78.78% vs +28.95%，end=2026-07-01）。
  → 单点回测无法区分“权重真的好”与“恰好抽到一组幸运噪声”。

本脚本的做法：
  保持权重方向（符号）不变，对每个 |w| 施加乘性均匀扰动 |w|·(1+U(-j, +j))，
  再归一化到基线的绝对值和（scale 不变，只扰动相对配比），逐组跑同口径回测，
  汇总 Sharpe / MaxDD / 超额收益 的分布，并计算每次首日持仓与基线的重叠度。

判读标准（约定）：
  - Sharpe 的 P10–P90 宽度 < 0.15 → 权重选择稳定，单点回测可信
  - Sharpe 的 P10–P90 宽度 > 0.40 → 噪声主导，不要用单点回测选权重
  - 首日重叠度中位数 < 7/10 → 组合由排序近并列翻转决定，同样属于噪声主导

用法：
  # 先看扰动计划，不跑回测
  python scripts/research/weight_perturbation_stability.py --dry-run

  # 正式跑（建议用 systemd-run 包一层，避免 4GiB 后台 cgroup 限制）
  systemd-run --user --scope -p MemoryMax=16G --quiet \\
      .venv/bin/python scripts/research/weight_perturbation_stability.py --runs 6 --jitter 0.10

输出：
  逐组明细 + 分位数汇总（loguru 打到 stderr）
  data/reports/weight_stability_<ts>.json（完整记录，含每次 experiment_id 便于追溯）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl
from loguru import logger

from qp.shared.json_io import json_load, json_save
from qp.shared.paths import EXPERIMENTS_DIR, REPORTS_DIR
from qp.shared.time import fmt_compact

REPO_ROOT = Path(__file__).resolve().parents[2]

# B 组权重（2026-08-14 三组对照最优，registry meta 现行）
B_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.23311635475996745,
    "Volatility_20D": 0.1822620016273393,
    "Momentum_3M": -0.2367778681855167,
    "Volume_Concentration": -0.1757526444263629,
    "Volume_Trend_10D": -0.17209113100081366,
}

# 旧 v20260811 生产权重（对照用）
V20260811_WEIGHTS: dict[str, float] = {
    "Amplitude_5D": -0.25,
    "Volatility_20D": 0.22,
    "Momentum_3M": -0.20,
    "Volume_Concentration": -0.19,
    "Volume_Trend_10D": -0.14,
}


@dataclass
class RunResult:
    """一次回测的记录。"""

    run_index: int
    label: str
    weights: dict[str, float]
    experiment_id: str
    sharpe: float
    max_drawdown_pct: float
    excess_return_pct: float
    total_return_pct: float
    ic_mean: float
    first_day_holdings: list[str]


def perturb_weights(
    base: dict[str, float], jitter: float, rng: np.random.Generator
) -> dict[str, float]:
    """保号乘性扰动 + 归一化到基线绝对值和。"""
    scaled: dict[str, float] = {}
    for name, value in base.items():
        factor = 1.0 + float(rng.uniform(-jitter, jitter))
        sign = -1.0 if value < 0 else 1.0
        scaled[name] = sign * abs(value) * factor

    target = sum(abs(v) for v in base.values())
    current = sum(abs(v) for v in scaled.values())
    if current <= 0:
        return dict(base)
    return {name: value * target / current for name, value in scaled.items()}


def _new_artifact(before: set[str], after: set[str]) -> str:
    new = sorted(after - before)
    if len(new) != 1:
        raise RuntimeError(f"预期恰好 1 个新实验产物，实际 {len(new)} 个：{new}")
    return new[0]


def _first_day_holdings(experiment_id: str) -> list[str]:
    """读 trade_log 首个交易日的持仓标的。"""
    trade_log = EXPERIMENTS_DIR / experiment_id / "trade_log.parquet"
    if not trade_log.exists():
        return []
    frame = pl.read_parquet(trade_log)
    if frame.is_empty() or "timestamp" not in frame.columns:
        return []
    first_day = frame["timestamp"].min()
    return sorted(frame.filter(pl.col("timestamp") == first_day)["symbol"].unique().to_list())


def run_one(
    *,
    run_index: int,
    run_total: int,
    label: str,
    weights: dict[str, float],
    strategy: str,
    start: str,
    end: str,
    top_n: int,
    rebalance: int,
    rebalance_offset: int,
    industry_neutral: bool,
    timeout: int,
) -> RunResult:
    """跑一次冻结权重回测并解析产物。"""
    pattern = "multifactor_*.json"
    before = {p.name for p in EXPERIMENTS_DIR.glob(pattern)}

    freeze = json.dumps(weights, separators=(",", ":"))
    cmd = [
        sys.executable,
        "-m",
        "qp.platform.cli.main",
        "experiment",
        "run",
        "multifactor",
        f"--strategy={strategy}",
        f"--start={start}",
        f"--end={end}",
        f"--top-n={top_n}",
        f"--rebalance={rebalance}",
        f"--rebalance-offset={rebalance_offset}",
        f"--freeze-weights={freeze}",
    ]
    if industry_neutral:
        cmd.append("--industry-neutral")

    logger.info("[{}/{}] {} — 权重: {}", run_index, run_total, label, freeze)
    # S603: 调的是本项目自己的 CLI 入口，argv 全部由本脚本构造，无外部输入拼接
    proc = subprocess.run(  # noqa: S603
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-15:])
        raise RuntimeError(f"{label} 回测失败（exit={proc.returncode}）：\n{tail}")

    after = {p.name for p in EXPERIMENTS_DIR.glob(pattern)}
    artifact = _new_artifact(before, after)
    experiment_id = artifact.removesuffix(".json")
    record = json_load(EXPERIMENTS_DIR / artifact)
    metrics = record["metrics"]

    return RunResult(
        run_index=run_index,
        label=label,
        weights=weights,
        experiment_id=experiment_id,
        sharpe=float(metrics["sharpe_ratio"]),
        max_drawdown_pct=float(metrics["max_drawdown_pct"]),
        excess_return_pct=float(metrics["excess_return_pct"]),
        total_return_pct=float(metrics["total_return_pct"]),
        ic_mean=float(metrics["ic_mean"]),
        first_day_holdings=_first_day_holdings(experiment_id),
    )


def _pctl(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values), q)) if values else float("nan")


def summarize(baseline: RunResult, runs: list[RunResult]) -> dict[str, object]:
    """汇总扰动组的分位数与持仓重叠度。"""
    sharpes = [r.sharpe for r in runs]
    drawdowns = [r.max_drawdown_pct for r in runs]
    excess = [r.excess_return_pct for r in runs]
    base_holdings = set(baseline.first_day_holdings)
    overlaps = [
        len(base_holdings & set(r.first_day_holdings)) / max(len(base_holdings), 1) for r in runs
    ]

    return {
        "baseline": {
            "experiment_id": baseline.experiment_id,
            "sharpe": baseline.sharpe,
            "max_drawdown_pct": baseline.max_drawdown_pct,
            "excess_return_pct": baseline.excess_return_pct,
            "total_return_pct": baseline.total_return_pct,
            "ic_mean": baseline.ic_mean,
            "first_day_holdings": baseline.first_day_holdings,
        },
        "perturbed": {
            "n": len(runs),
            "sharpe": {
                "min": min(sharpes),
                "p10": _pctl(sharpes, 10),
                "p50": _pctl(sharpes, 50),
                "p90": _pctl(sharpes, 90),
                "max": max(sharpes),
                "p10_p90_width": _pctl(sharpes, 90) - _pctl(sharpes, 10),
            },
            "max_drawdown_pct": {
                "min": min(drawdowns),
                "p50": _pctl(drawdowns, 50),
                "max": max(drawdowns),
            },
            "excess_return_pct": {
                "min": min(excess),
                "p50": _pctl(excess, 50),
                "max": max(excess),
            },
            "first_day_overlap": {
                "min": min(overlaps),
                "p50": _pctl(overlaps, 50),
                "max": max(overlaps),
            },
        },
        "verdict": _verdict(sharpes, overlaps),
    }


def _verdict(sharpes: list[float], overlaps: list[float]) -> str:
    """按脚本头部约定的判读标准给出结论。"""
    width = _pctl(sharpes, 90) - _pctl(sharpes, 10)
    overlap_median = _pctl(overlaps, 50)
    if width < 0.15 and overlap_median >= 0.8:
        return "STABLE: 权重选择稳定，单点回测可信"
    if width > 0.40 or overlap_median < 0.7:
        return "NOISE-DOMINATED: 噪声主导，不要用单点回测选权重"
    return "MARGINAL: 边界情况，需扩大扰动组数或换窗口复核"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="权重扰动稳定性检验（冻结权重逐组回测）")
    parser.add_argument("--strategy", default="momentum_vol_full")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--rebalance-offset", type=int, default=6)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--rebalance", type=int, default=20)
    parser.add_argument("--no-industry-neutral", action="store_true")
    parser.add_argument("--runs", type=int, default=6, help="扰动组数（不含基线）")
    parser.add_argument("--jitter", type=float, default=0.10, help="乘性扰动幅度，0.10 = ±10%")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=1200, help="单次回测超时秒数")
    parser.add_argument(
        "--base",
        choices=["b_group", "v20260811"],
        default="b_group",
        help="基线权重集",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印扰动计划，不跑回测")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    base = B_WEIGHTS if args.base == "b_group" else V20260811_WEIGHTS
    rng = np.random.default_rng(args.seed)

    plan: list[tuple[str, dict[str, float]]] = [("baseline", dict(base))]
    plan.extend(
        (
            f"jitter{i + 1:02d}",
            perturb_weights(base, args.jitter, rng),
        )
        for i in range(args.runs)
    )

    logger.info(
        "窗口 start={} end={} offset={} | 基线={} | 扰动 ±{:.0%} × {} 组 | seed={}",
        args.start,
        args.end,
        args.rebalance_offset,
        args.base,
        args.jitter,
        args.runs,
        args.seed,
    )
    for label, weights in plan:
        logger.info("  {}: {}", label, json.dumps(weights, separators=(",", ":")))

    if args.dry_run:
        logger.info("dry-run：未执行回测")
        return 0

    results: list[RunResult] = []
    for index, (label, weights) in enumerate(plan, start=1):
        results.append(
            run_one(
                run_index=index,
                run_total=len(plan),
                label=label,
                weights=weights,
                strategy=args.strategy,
                start=args.start,
                end=args.end,
                top_n=args.top_n,
                rebalance=args.rebalance,
                rebalance_offset=args.rebalance_offset,
                industry_neutral=not args.no_industry_neutral,
                timeout=args.timeout,
            )
        )
        latest = results[-1]
        logger.info(
            "    → {} | Sharpe {:.2f} | MaxDD {:.2f}% | 超额 {:+.2f}% | 收益 {:+.2f}%",
            latest.experiment_id,
            latest.sharpe,
            latest.max_drawdown_pct,
            latest.excess_return_pct,
            latest.total_return_pct,
        )

    baseline, perturbed = results[0], results[1:]
    summary = summarize(baseline, perturbed)
    summary["config"] = {
        "strategy": args.strategy,
        "start": args.start,
        "end": args.end,
        "rebalance_offset": args.rebalance_offset,
        "top_n": args.top_n,
        "rebalance": args.rebalance,
        "industry_neutral": not args.no_industry_neutral,
        "base": args.base,
        "jitter": args.jitter,
        "runs": args.runs,
        "seed": args.seed,
    }
    summary["runs"] = [
        {
            "label": r.label,
            "experiment_id": r.experiment_id,
            "weights": r.weights,
            "sharpe": r.sharpe,
            "max_drawdown_pct": r.max_drawdown_pct,
            "excess_return_pct": r.excess_return_pct,
            "total_return_pct": r.total_return_pct,
            "first_day_holdings": r.first_day_holdings,
        }
        for r in results
    ]

    out_path = json_save(REPORTS_DIR / f"weight_stability_{fmt_compact()}.json", summary)

    stats = summary["perturbed"]
    assert isinstance(stats, dict)
    sharpe_stats = stats["sharpe"]
    overlap_stats = stats["first_day_overlap"]
    assert isinstance(sharpe_stats, dict) and isinstance(overlap_stats, dict)
    logger.info("=" * 74)
    logger.info(
        "基线 Sharpe {:.2f} / MaxDD {:.2f}% / 超额 {:+.2f}%",
        baseline.sharpe,
        baseline.max_drawdown_pct,
        baseline.excess_return_pct,
    )
    logger.info(
        "扰动组 Sharpe: min {:.2f} | P10 {:.2f} | P50 {:.2f} | P90 {:.2f} | max {:.2f} | 宽度 {:.2f}",
        sharpe_stats["min"],
        sharpe_stats["p10"],
        sharpe_stats["p50"],
        sharpe_stats["p90"],
        sharpe_stats["max"],
        sharpe_stats["p10_p90_width"],
    )
    logger.info(
        "首日持仓与基线重叠: min {:.0%} | P50 {:.0%} | max {:.0%}",
        overlap_stats["min"],
        overlap_stats["p50"],
        overlap_stats["max"],
    )
    logger.info("结论: {}", summary["verdict"])
    logger.info("明细已写入 {}", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
