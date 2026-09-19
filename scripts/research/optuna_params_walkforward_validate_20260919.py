"""Optuna 最优参数的**时间序（walk-forward）外推验证** —— TDR-005 / tracker §#1 收尾。

背景
----
`qp experiment optuna` 的目标函数是 **PurgedKFold（随机折）OOS IC**：8/13 搜出
best −0.0444 vs baseline −0.0572（改善 ~22%，30 trials）。但随机折不能完全排除
折间信息泄漏，TDR-005 明确要求：短样本最优参数进生产前必须过**完整 walk-forward**。

本脚本做的是 **expanding-window 时间序验证**：
  train ≤ 2019..N 年 → test N+1 年（逐年滚动，绝不回头）
对 baseline（DEFAULT_LGB_PARAMS）与 best（8/13 Optuna 结果）各训一次，
比较每年的 OOS Spearman IC，并给出样本内/外 IC 比（过拟合检查）。

用法
----
    .venv/bin/python scripts/research/optuna_params_walkforward_validate_20260919.py \
        --start 2019-01-01 --end 2025-12-31 [--max-stocks 800] [--min-train-years 3]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from qp.research.feature.compute import PRICE_VOLUME_FACTORS, compute_all_factors  # noqa: E402
from qp.research.model_trainer import FEATURES, WalkForwardScorer  # noqa: E402
from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS, LightGBMRankModel  # noqa: E402
from qp.shared.paths import OPTUNA_DIR  # noqa: E402

# 可作为超参传递的键（OptunaResult.best_params 里混了 objective/metric 等固定键）
TUNABLE_KEYS = {
    "num_leaves",
    "max_depth",
    "learning_rate",
    "min_data_in_leaf",
    "feature_fraction",
    "bagging_fraction",
    "lambda_l1",
    "lambda_l2",
    "n_estimators",
    "min_child_samples",
}


def _spearman(pred: np.ndarray, target: np.ndarray) -> float:
    """Spearman 秩相关（与 WalkForwardScorer / OptunaSearch 口径一致）。"""
    if len(pred) < 3:
        return float("nan")
    r_pred = np.argsort(np.argsort(pred))
    r_target = np.argsort(np.argsort(target))
    if r_pred.std() < 1e-12 or r_target.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(r_pred, r_target)[0, 1])


def _load_flat_df(args: argparse.Namespace) -> Any:
    """复用 `qp experiment optuna` 的数据组装路径（同样本、同标签）。"""
    from qp.pipeline.multifactor_pipeline import MultiFactorPipeline

    print(f"📥 加载数据: {args.dataset} ({args.start} → {args.end})", flush=True)
    price_data = MultiFactorPipeline._fetch_data([], args.start, args.end, args.dataset)
    if not price_data:
        raise SystemExit("❌ 数据为空")
    print(f"   {len(price_data)} 只股票", flush=True)

    if args.max_stocks and len(price_data) > args.max_stocks:
        import random

        rng = random.Random(args.seed)  # noqa: S311 — 抽样非加密用途，seed 固定保证可复现
        codes = rng.sample(sorted(price_data.keys()), args.max_stocks)
        price_data = {c: price_data[c] for c in codes}
        print(f"   🎲 抽样 {args.max_stocks} 只（seed={args.seed}）", flush=True)

    print("🧮 计算原始因子...", flush=True)
    all_raw: dict[str, dict[str, dict[str, float]]] = {}
    for code, df in price_data.items():
        try:
            factors = compute_all_factors(df.sort("trade_date"))
        except Exception:
            continue
        if factors.is_empty():
            continue
        for row in factors.iter_rows(named=True):
            date_str = str(row["trade_date"])
            all_raw.setdefault(date_str, {})[code] = {
                f: float(row[f]) for f in PRICE_VOLUME_FACTORS if f in row
            }
    print(f"   原始因子: {len(all_raw)} 天截面", flush=True)

    scorer = WalkForwardScorer(train_window_days=args.train_window)
    flat_df = scorer._build_flat_dataset(all_raw, price_data)
    if flat_df.is_empty():
        raise SystemExit("❌ flat 数据集为空")
    print(f"   数据集: {flat_df.height} 行, {flat_df['date'].n_unique()} 天", flush=True)
    return flat_df


def _load_best_params() -> tuple[dict[str, Any], Path]:
    files = sorted(OPTUNA_DIR.glob("lgb_optuna_*.json"))
    if not files:
        raise SystemExit(f"❌ 未找到 Optuna 结果: {OPTUNA_DIR}/lgb_optuna_*.json")
    latest = files[-1]
    payload = json.loads(latest.read_text(encoding="utf-8"))
    raw = payload.get("best_params", {}) or {}
    return {k: v for k, v in raw.items() if k in TUNABLE_KEYS}, latest


def _train_eval(
    train_df: Any,
    test_df: Any,
    active_features: list[str],
    params: dict[str, Any],
) -> tuple[float, float]:
    """训练一次并返回 (样本内 IC, 样本外 IC)。

    flat 数据集是 polars；`LightGBMRankModel.fit` 吃 pandas（与 model_trainer
    内部一致），故此处转换，并用 `groupby("date").size()` 给出 LambdaRank 的组大小。
    """
    pdf_train = train_df.to_pandas()
    pdf_test = test_df.to_pandas()
    groups = pdf_train.groupby("date").size().to_numpy()

    model = LightGBMRankModel()
    model._params = {**DEFAULT_LGB_PARAMS, **params}
    model._params["verbose"] = -1
    model._params["num_boost_round"] = 100
    model.fit(
        pdf_train[active_features].astype(np.float64),
        pdf_train["label"].astype(np.float64),
        groups=groups,
    )
    is_pred = np.asarray(model.predict(pdf_train[active_features].astype(np.float64)))
    oos_pred = np.asarray(model.predict(pdf_test[active_features].astype(np.float64)))
    return (
        _spearman(is_pred, pdf_train["label"].to_numpy(dtype=float)),
        _spearman(oos_pred, pdf_test["label"].to_numpy(dtype=float)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--dataset", default="daily_price_latest")
    parser.add_argument("--max-stocks", type=int, default=0)
    parser.add_argument("--train-window", type=int, default=252)
    parser.add_argument("--min-train-years", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    best_params, src = _load_best_params()
    print(f"📄 Optuna 结果: {src.name}")
    print(f"   best 覆盖超参: {best_params}", flush=True)
    print(f"   baseline: {DEFAULT_LGB_PARAMS}", flush=True)

    flat_df = _load_flat_df(args)
    active_features = [f for f in FEATURES if f in flat_df.columns]
    if not active_features:
        raise SystemExit("❌ 无可用特征列")

    years = sorted({int(str(d)[:4]) for d in flat_df["date"].unique().to_list()})
    print(f"📆 年份: {years}", flush=True)

    rows: list[dict[str, Any]] = []
    for test_year in years[args.min_train_years :]:
        train_df = flat_df.filter(flat_df["date"].cast(str).str.slice(0, 4).cast(int) < test_year)
        test_df = flat_df.filter(flat_df["date"].cast(str).str.slice(0, 4).cast(int) == test_year)
        if train_df.height < 5000 or test_df.height < 100:
            print(f"  跳过 {test_year}: 样本不足 (train={train_df.height}, test={test_df.height})")
            continue
        row: dict[str, Any] = {
            "test_year": test_year,
            "train_rows": train_df.height,
            "test_rows": test_df.height,
        }
        for tag, params in (("baseline", {}), ("best", best_params)):
            t0 = time.time()
            is_ic, oos_ic = _train_eval(train_df, test_df, active_features, params)
            row[f"{tag}_is_ic"] = round(is_ic, 4)
            row[f"{tag}_oos_ic"] = round(oos_ic, 4)
            # A 股价量因子的 IC 常为负（direction=-1 是正常反向信号）→ 预测强度看 |IC|
            row[f"{tag}_is_abs"] = round(abs(is_ic), 4)
            row[f"{tag}_oos_abs"] = round(abs(oos_ic), 4)
            row[f"{tag}_secs"] = round(time.time() - t0, 1)
            print(
                f"  {test_year} {tag:8s} IS={is_ic:+.4f} OOS={oos_ic:+.4f} "
                f"|OOS|={abs(oos_ic):.4f} ({row[f'{tag}_secs']}s)",
                flush=True,
            )
        row["oos_abs_delta"] = round(row["best_oos_abs"] - row["baseline_oos_abs"], 4)
        rows.append(row)

    if not rows:
        raise SystemExit("❌ 没有任何可评估的年份（数据窗口不足）")

    print("\n=== 时间序（expanding window）验证结果 ===")
    print(
        f"{'year':>6} {'base |OOS|':>11} {'best |OOS|':>11} {'Δ|OOS|':>8} "
        f"{'base OOS':>9} {'best OOS':>9} {'best IS':>9}"
    )
    for r in rows:
        print(
            f"{r['test_year']:>6} {r['baseline_oos_abs']:>11.4f} {r['best_oos_abs']:>11.4f} "
            f"{r['oos_abs_delta']:>+8.4f} {r['baseline_oos_ic']:>+9.4f} "
            f"{r['best_oos_ic']:>+9.4f} {r['best_is_ic']:>+9.4f}"
        )
    base_mean = float(np.mean([r["baseline_oos_abs"] for r in rows]))
    best_mean = float(np.mean([r["best_oos_abs"] for r in rows]))
    wins = sum(1 for r in rows if r["oos_abs_delta"] > 0)
    print(
        f"\n均值 |OOS IC|: baseline {base_mean:.4f} | best {best_mean:.4f} | "
        f"Δ {best_mean - base_mean:+.4f}（A 股价量因子 IC 为负属正常，强度看 |IC|）"
    )
    print(f"best 胜出年份（按 |OOS IC|）: {wins}/{len(rows)}")

    out = OPTUNA_DIR / f"walkforward_validation_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(
        json.dumps(
            {
                "source": src.name,
                "best_params": best_params,
                "baseline_params": DEFAULT_LGB_PARAMS,
                "rows": rows,
                "mean_abs_oos_ic": {"baseline": base_mean, "best": best_mean},
                "wins_by_abs_oos_ic": f"{wins}/{len(rows)}",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\n💾 结果保存: {out}")
    print("⚠️ 结论口径: 只有 best 在多数年份 OOS 稳定胜出，才值得改写 DEFAULT_LGB_PARAMS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
