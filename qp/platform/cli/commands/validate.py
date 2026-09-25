"""CLI command handlers for the "validate" group.

指标来源（2026-09-25 起）：回测指标一律来自**真实实验记录**
（``ExperimentTracker`` / ``data/experiments/<id>.json``），不再使用写死的占位值。
找不到可用实验 → 报错退出，而不是拿假数字跑门禁。
"""

from __future__ import annotations

import sys
from typing import Any

from qp.shared.paths import MOMENTUM_20D, resolve_daily_price_path

# 规则详情里出现这些字样 = 该指标在数据源里不存在 → 检查项未评估（≠ 通过）
_NOT_EVALUATED_MARKERS = (
    "not available",
    "in validation context",
    "in context.metadata",
    "in backtest_metrics",
    "skipping",
    "not computed",
)

# 基础回测指标（其余键就是"追加指标"，打印出来方便核对这次门禁吃了哪些实测值）
_BASE_METRIC_KEYS = frozenset({"sharpe_ratio", "max_drawdown_pct", "total_return_pct"})


def _resolve_default_strategy_id() -> tuple[str | None, str]:
    """返回「当前该被校验的策略」：registry 里唯一 APPROVED 的那个（见 registry 助手）。"""
    from qp.strategy.registry import resolve_single_approved_strategy_id

    return resolve_single_approved_strategy_id()


def _created_at(record: Any) -> str:
    """实验创建时间（ISO 字符串）。"""
    created = getattr(getattr(record, "config", None), "created_at", None)
    if created is None:
        return "unknown"
    return created.isoformat() if hasattr(created, "isoformat") else str(created)


def _load_experiment_record(strategy_id: str, experiment_id: str) -> tuple[Any | None, str]:
    """定位提供真实回测指标的实验记录。

    选择规则：
      - 显式 ``--experiment <id>`` → 取该记录（不存在则报错）
      - 否则取 ``config.strategy_name == strategy_id`` 中**最新**的一条

    ⚠️ 不能用 ``ExperimentTracker.get_latest(strategy_id)``：它按
    ``record.lineage.strategy_id`` 过滤，而该字段存的是内部名
    （如 ``multifactor_top10``），永远匹配不上 registry 里的策略 ID。

    Returns:
        ``(record, reason)``；无法提供真实指标时 record 为 None，reason 说明原因。
    """
    from qp.research.experiment.tracker import ExperimentTracker

    tracker = ExperimentTracker()

    if experiment_id:
        record = tracker.get(experiment_id)
        if record is None:
            return None, f"实验不存在 / experiment not found: {experiment_id}"
    else:
        matches = [r for r in tracker.list_experiments() if r.config.strategy_name == strategy_id]
        if not matches:
            return None, (
                f"没有 '{strategy_id}' 的实验记录 / no experiment for this strategy — "
                f"先跑 qp experiment run multifactor --strategy {strategy_id}，"
                "或用 --experiment <id> 指定"
            )
        record = matches[0]  # list_experiments() 按 created_at 倒序

    metrics = record.metrics
    if metrics.n_days <= 0:
        return None, (
            f"实验 {record.config.experiment_id} 没有回测结果（n_days=0）/ no backtest in this "
            "experiment — 无法校验回测类规则"
        )
    return record, ""


def _build_context(
    record: Any,
    feature_df: Any,
    price_df: Any,
) -> Any:
    """用实验记录里的**实测值**构造 ValidationContext。

    只放真实存在的键：实验记录里没有生产者的指标一律不塞占位值 ——
    对应检查项会走自己的"缺数据"分支，输出里能看到它没被评估。

    指标 → 检查项映射（2026-09-25 补齐，让门禁可评估）：
      - ``sharpe_ratio`` / ``max_drawdown_pct``：权益曲线口径（本身含成本）
      - ``sharpe_ratio_net`` / ``max_drawdown_pct_net`` / ``total_cost_pct`` → CostAdjustedCheck
      - ``daily_turnover_pct``（= 累计换手 / 交易日数）→ TurnoverCheck
      - ``pre/post_neutralization_ic``（仅 legacy 因子管线路径有值）→ NeutralizationCheck
      - ``ic_mean`` / ``custom.cv_oos_ic_mean``（全期 IC vs Purged-CV OOS IC）→ OverfitCheck
      - ``feature_importance``（线性策略 = 归一化 |权重|）→ FeatureImportanceCheck
    """
    import polars as pl

    from qp.validation.engine import ValidationContext

    metrics = record.metrics
    backtest_metrics: dict[str, float] = {
        "sharpe_ratio": float(metrics.sharpe_ratio),
        "max_drawdown_pct": float(metrics.max_drawdown_pct),
        "total_return_pct": float(metrics.total_return_pct),
    }
    # 成本口径 / 派生指标：只在真有值时进 ctx（0 = 该实验没算，别当成"零成本/零换手"）
    for key, value in (
        ("sharpe_ratio_net", metrics.sharpe_ratio_net),
        ("max_drawdown_pct_net", metrics.max_drawdown_pct_net),
        ("total_cost_pct", metrics.total_cost_pct),
        ("daily_turnover_pct", metrics.daily_turnover_pct),
    ):
        if value:
            backtest_metrics[key] = float(value)

    metadata: dict[str, Any] = {
        "experiment_id": record.config.experiment_id,
        "train_start": record.config.train_start,
        "train_end": record.config.train_end,
    }

    # 中性化前后 IC（legacy 因子管线路径才落这两项）
    if metrics.pre_neutralization_ic and metrics.post_neutralization_ic:
        metadata["pre_neutralization_ic"] = float(metrics.pre_neutralization_ic)
        metadata["post_neutralization_ic"] = float(metrics.post_neutralization_ic)

    # 过拟合：全期 IC 视作 in-sample，Purged-CV OOS IC 视作 out-of-sample
    oos_ic = float(metrics.custom.get("cv_oos_ic_mean", 0.0) or 0.0)
    if metrics.ic_mean and oos_ic:
        metadata["in_sample_ic"] = float(metrics.ic_mean)
        metadata["out_of_sample_ic"] = oos_ic
        metadata["ic_source"] = "ic_mean(full-period) vs cv_oos_ic_mean(purged-CV OOS)"

    # 特征重要性：dict → [feature, gain] 表，按 gain 降序（检查项取 gains[0] 当 top1）
    importance = metrics.feature_importance or {}
    if importance:
        ranked = sorted(importance.items(), key=lambda kv: kv[1], reverse=True)
        metadata["feature_importance"] = pl.DataFrame(
            {"feature": [k for k, _ in ranked], "gain": [float(v) for _, v in ranked]}
        )

    return ValidationContext(
        feature_df=feature_df,
        price_df=price_df,
        signal_df=None,
        backtest_metrics=backtest_metrics,
        strategy_id=record.config.strategy_name or record.config.experiment_id,
        metadata=metadata,
    )


def cmd_validate() -> int:
    """Run validation gate checks on the current strategy.

    Usage:
        qp validate                          # 默认策略 = registry 唯一 APPROVED
        qp validate --stage backtest_passed  # 指定阶段
        qp validate --strategy-id <id>       # 指定策略
        qp validate --experiment <id>        # 指定提供指标的实验记录
        qp validate --json                   # 机器可读输出（含指标来源）
    """
    import json as _json

    import polars as pl

    from qp.validation import ValidationPipeline, ValidationPipelineConfig

    # Parse flags
    stage = "backtest_passed"
    strategy_id = ""  # 空 → 解析为 registry 中唯一 APPROVED 的策略
    experiment_id = ""
    json_output = False

    args = sys.argv
    i = 2  # skip "qp" and "validate"
    while i < len(args):
        if args[i] == "--stage" and i + 1 < len(args):
            stage = args[i + 1]
            i += 2
        elif args[i] == "--strategy-id" and i + 1 < len(args):
            strategy_id = args[i + 1]
            i += 2
        elif args[i] == "--experiment" and i + 1 < len(args):
            experiment_id = args[i + 1]
            i += 2
        elif args[i] == "--json":
            json_output = True
            i += 1
        else:
            i += 1

    valid_stages = {
        "research",
        "backtest_passed",
        "paper_trading",
        "shadow_production",
        "production",
    }

    def _fail(message: str) -> int:
        if json_output:
            print(_json.dumps({"status": "error", "message": message}, ensure_ascii=False))
        else:
            print(f"❌ {message}")
        return 1

    if stage not in valid_stages:
        return _fail(f"Invalid stage: '{stage}'. Valid: {', '.join(sorted(valid_stages))}")

    if not strategy_id:
        strategy_id, why = _resolve_default_strategy_id()
        if strategy_id is None:
            return _fail(why)

    # 指标来源：真实实验记录（无记录即失败，不用占位值）
    record, why = _load_experiment_record(strategy_id, experiment_id)
    if record is None:
        return _fail(why)

    # Load data — freshest daily price snapshot on disk (see resolve_daily_price_path)
    try:
        feature_df = pl.read_parquet(MOMENTUM_20D)
        price_df = pl.read_parquet(str(resolve_daily_price_path()))
    except FileNotFoundError as e:
        return _fail(f"Data not found. Run 'qp run daily' first. ({e})")

    # Ensure date types match
    feature_df = feature_df.with_columns(pl.col("trade_date").cast(pl.Date))
    price_df = price_df.with_columns(pl.col("trade_date").cast(pl.Date))

    config = ValidationPipelineConfig(
        stage=stage,
        strategy_id=strategy_id,
        overrides={},  # Use defaults — override via config file in future
    )
    pipeline = ValidationPipeline(config=config)
    ctx = _build_context(record, feature_df, price_df)

    if not json_output:
        metrics = record.metrics
        print(f"=== QP Validation Gate ({stage}) ===")
        print(f"  策略 / Strategy:       {strategy_id}")
        print(f"  实验 / Experiment:     {record.config.experiment_id} ({_created_at(record)})")
        print(
            "  实测指标 / Measured:   "
            f"sharpe={metrics.sharpe_ratio:g} | max_dd={metrics.max_drawdown_pct:g}% | "
            f"total_return={metrics.total_return_pct:g}% | n_days={metrics.n_days}"
        )
        extra = sorted(k for k in ctx.backtest_metrics if k not in _BASE_METRIC_KEYS)
        if extra:
            print(
                "  追加指标 / Extra:      "
                + " | ".join(f"{k}={ctx.backtest_metrics[k]:g}" for k in extra)
            )
        provenance: list[str] = []
        if "ic_source" in ctx.metadata:
            provenance.append(f"overfit IC 口径: {ctx.metadata['ic_source']}")
        if "feature_importance" in ctx.metadata:
            provenance.append("importance: 归一化 |权重| (线性策略)")
        if "pre_neutralization_ic" in ctx.metadata:
            provenance.append("neutralization: 管线 pre/post IC 实测")
        if provenance:
            print("  口径 / Provenance:     " + " ; ".join(provenance))
        print()

    result = pipeline.run(ctx)
    validation = result.metadata.get("validation", {})
    rules = validation.get("rules", [])

    # 哪些检查项因为"指标不存在"而没被真正评估
    not_evaluated = [
        r.get("rule_name", "?")
        for r in rules
        if any(m in str(r.get("detail", "")) for m in _NOT_EVALUATED_MARKERS)
    ]

    if json_output:
        out = {
            "stage": stage,
            "strategy_id": strategy_id,
            "status": result.status.value,
            "validation": validation,
            "recommendation": result.metadata.get("recommendation", ""),
            "metrics_source": f"experiment:{record.config.experiment_id}",
            "experiment_id": record.config.experiment_id,
            "experiment_created_at": _created_at(record),
            "not_evaluated_rules": not_evaluated,
        }
        print(_json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Strategy:   {strategy_id}")
        print(f"Stage:      {stage}")
        print(f"Overall:    {validation.get('status', 'unknown').upper()}")
        print(f"Score:      {validation.get('score', 0)}/100")
        print(f"Confidence: {validation.get('confidence', 0):.0%}")
        print()

        if rules:
            print(f"Checks ({len(rules)} total):")
            for r in rules:
                icon = "✅" if r.get("status") == "pass" else "❌"
                print(f"  {icon} {r.get('rule_name', '?'):<24s}  {r.get('detail', '')}")

        failed = validation.get("failed_rules", [])
        if failed:
            print()
            print(f"Failed: {len(failed)}/{len(rules)} rules — {', '.join(failed)}")
            rec = result.metadata.get("recommendation", "")
            if rec:
                print(f"Recommendation: {rec}")
        elif rules:
            print()
            print("All checks passed — strategy may proceed to the next stage.")

        if not_evaluated:
            print()
            print(
                f"⚠️  {len(not_evaluated)} 项未评估（该指标在实验记录里不存在，"
                f"不代表通过）: {', '.join(not_evaluated)}"
            )

    return 0 if result.status.value == "success" else 1
