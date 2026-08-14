"""MultiFactorPipeline — multi-factor strategy experiment as a BasePipeline.

End-to-end experiment conforming to ADR-006 ("Everything is a Pipeline"):

  Raw Ingestion              TencentAdapter.fetch_raw()
       │
  Cleaning (4-stage ETL)     ETLPipeline: anomaly→volume→suspension→adjustment
       │
  Repair                     OHLC boundaries, amount validation, missing dates
       │
  Validation                 DailyPriceContract schema check
       │
  PIT & Universe             Suspension + delisted filtering
       │
  Feature Compute            15 price/volume factors (momentum, vol, volume, money flow)
       │
  Cross-sectional Scoring    Winsorize → Normalize → Combine → Rank
       │
  IC Analysis                Spearman Rank IC, ICIR, IC>0 ratio
       │
  Signal Generation          Top-N monthly rebalance with sell buffer
       │
  Backtest + Benchmark       Equal-weight backtest vs buy-and-hold

Usage via CLI:
    qp experiment run multifactor \\
        --symbols 000001,000002,... \\
        --start 2024-01-01 --end 2026-07-20 \\
        --top-n 10 --rebalance 20 \\
        --industry-neutral --orthogonalize
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import polars as pl
from loguru import logger

from qp.data.dataset.registry import DatasetRegistry
from qp.platform.pipeline.context import PipelineContext
from qp.platform.pipeline.result import PipelineResult
from qp.research.evaluation.layered_test import compute_layered_returns
from qp.research.evaluation.rank_ic import evaluate_factor_ic
from qp.research.factor_processor import factor_pipeline
from qp.research.feature.compute import (
    ALL_FACTOR_DIRECTIONS,
    PRICE_VOLUME_FACTORS,
    compute_all_factors,
)
from qp.shared.protocols.base_pipeline import BasePipeline
from qp.shared.types import PipelineStatus, StrategyLifecycle
from qp.strategy.multifactor import generate_rebalance_signals

if TYPE_CHECKING:
    from qp.research.evaluation.layered_test import LayeredTestResult
    from qp.research.evaluation.rank_ic import ICRecord
    from qp.strategy.config import StrategyConfig

# Default stock pool: liquid large-cap + representative sectors
DEFAULT_SYMBOLS = [
    "000001",
    "000002",
    "000333",
    "000651",
    "000858",
    "002415",
    "002475",
    "300750",
    "600000",
    "600036",
    "600276",
    "600519",
    "600585",
    "600887",
    "601012",
    "601166",
    "601318",
    "601888",
]


class MultiFactorPipeline(BasePipeline):
    """Run a multi-factor strategy experiment on real A-share data.

    Pipeline stages:
      1. Fetch OHLCV data via TencentAdapter
      2. Compute cross-sectional factor scores
      3. Rank IC analysis (Spearman, forward 5-day)
      4. Generate rebalance signals (monthly, Top-N)
      5. Simple backtest (equal-weight, signal-day rebalance)
      6. Benchmark comparison (equal-weight buy-and-hold)

    Results are logged via Loguru and returned in PipelineResult.metrics.
    """

    @property
    def name(self) -> str:
        return "multifactor_experiment"

    # ------------------------------------------------------------------
    # Pipeline entry point
    # ------------------------------------------------------------------

    def run(self, context: PipelineContext) -> PipelineResult:
        params = context.parameters

        # Use runtime logger when available (ADR-012), fall back to bare loguru
        logger = context.logger

        symbols: list[str] = params.get("symbols", [])  # empty = all stocks in dataset
        start_date_str: str = params.get("start_date", "2024-01-01")
        end_date_str: str = params.get("end_date", date.today().isoformat())
        top_n: int = int(params.get("top_n", 10))
        rebalance_freq: int = int(params.get("rebalance_freq", 20))
        sell_buffer: int = int(params.get("sell_buffer_rank", 5))
        industry_neutral: bool = params.get("industry_neutral", False)
        orthogonalize: bool = params.get("orthogonalize", False)
        dataset: str = params.get("dataset", "daily_price_latest")
        data_snapshot: str = params.get("data_snapshot", "")  # path to price_data.parquet
        freeze_weights: dict[str, float] | None = params.get("freeze_weights", None)
        strategy_name: str = params.get("strategy", "default")
        skip_gate: bool = params.get("skip_gate", False)
        model_mode: bool = params.get("model_mode", False)
        score_band: str | None = params.get("score_band", None)  # e.g. "60-80" = Q4 only
        max_stocks: int = int(params.get("max_stocks", 0))  # 0 = all (memory guard)

        # ── Strategy mode ──
        use_full_strategy = strategy_name in (
            "momentum_vol_full",
            "mvf",
            "mv_full",
            "full",
            "low_vol_reversal",
            "lvr",
            "lvr_vol_only",
            "lvr_vol_stable",
            "lvr_vol_mom1m",
            "lvr_vol_conc",
            "lvr_vol_mom",
            "lvr_vol_all_rev",
            "mvf_v2_expansion",
            "mvf_v2_amount",
            "mvf_v2_interaction",
            "mvf_noorth",
            "alpha_multi_factor_v1",
            "alpha_multi_factor_v2",
            "alpha_ensemble_v2",
            "alpha_ensemble_v3",
        )

        result = PipelineResult(
            status=PipelineStatus.SUCCESS,
            pipeline_name=self.name,
            run_id=context.run_id,
        )

        logger.info("=" * 70)
        if use_full_strategy:
            from qp.strategy.config import get_strategy_config as _get_cfg

            try:
                _cfg = _get_cfg(strategy_name)
                _label = _cfg.display_name or strategy_name
            except KeyError:
                _label = strategy_name
            logger.info("多因子策略实验 — {} ({})", _label, strategy_name)
        else:
            logger.info("多因子策略实验 — A股真实数据")
        logger.info("=" * 70)
        n = len(symbols) if symbols else "全部"
        engine_label = "策略引擎" if use_full_strategy else "裸因子管线"
        logger.info(
            "股票池: {} 只 | 区间: {} → {} | Top-{} 每月调仓 | {}",
            n,
            start_date_str,
            end_date_str,
            top_n,
            engine_label,
        )
        if use_full_strategy:
            logger.info("质量过滤: ✅ | 行业中性: ✅ | 正交化: ✅ | 防追高: ✅ | 大盘过滤: ✅")
        elif industry_neutral:
            logger.info("行业中性化: ✅ | 因子正交化: {}", "✅" if orthogonalize else "❌")

        # ML 模式：需要额外历史数据用于训练
        fetch_start = start_date_str
        if model_mode:
            from datetime import datetime as _dt
            from datetime import timedelta as _td

            # 训练最少 252 天 + 25 天 gap ≈ 1.5 年
            ml_start = _dt.fromisoformat(start_date_str) - _td(days=600)
            fetch_start = ml_start.strftime("%Y-%m-%d")
            logger.info("   🤖 ML 模式: 数据加载从 {} 起 (训练窗口)", fetch_start)

        # ── Stage 1: Fetch data ──
        logger.info("[1/6] 获取行情数据...")
        try:
            if data_snapshot:
                price_data = self._load_snapshot(data_snapshot, symbols, fetch_start, end_date_str)
                logger.info("   📸 从实验快照加载: {}", data_snapshot)
            else:
                price_data = self._fetch_data(
                    symbols, fetch_start, end_date_str, dataset, max_stocks=max_stocks
                )
        except Exception as e:
            logger.error("数据获取失败: {}", e)
            result.status = PipelineStatus.FAILED
            result.errors.append(f"数据获取失败: {e}")
            return result

        if not price_data:
            logger.error("数据为空 — 请检查数据集名称是否正确 (--dataset)")
            logger.error("可用数据集: qp data 命令或查看 data/dataset/registry.json")
            result.status = PipelineStatus.FAILED
            result.errors.append("数据为空 — 数据集不存在或无数据")
            return result

        total_rows = sum(df.height for df in price_data.values())
        logger.info("   {} 只股票, {} 行日线数据", len(price_data), total_rows)
        result.metrics["n_stocks"] = float(len(price_data))
        result.metrics["n_rows"] = float(total_rows)
        result.metrics["model_mode"] = float(model_mode)

        # ── Stage 2: Factor computation / Strategy execution ──
        signals: pl.DataFrame = pl.DataFrame()
        extra_factors: dict | None = None

        # Build frozen config override for experiment reproduction
        frozen_override: StrategyConfig | None = None
        if freeze_weights:
            frozen_override = _build_optimized_config(strategy_name, dict(freeze_weights))
            if frozen_override:
                logger.info("   🔒 权重冻结 (复现模式): {}", freeze_weights)

        # CLI experiment overrides applied onto a config copy (never mutate
        # the registered strategy config).
        cli_overrides: dict[str, Any] = {
            key: params[key]
            for key in (
                "orthogonalize",
                "quality_filter",
                "industry_neutral",
                "anti_chase",
                "model_mode",
                "max_positions",
                "rebalance_freq",
            )
            if key in params
        }

        if use_full_strategy:
            (
                signals,
                scores,
                fundamental_data,
                valuation_data,
                index_df,
                extra_factors,
            ) = self._run_full_strategy(
                price_data=price_data,
                top_n=top_n,
                rebalance_freq=rebalance_freq,
                sell_buffer=sell_buffer,
                strategy_name=strategy_name,
                model_mode=model_mode,
                config_override=frozen_override,
                score_band=score_band,
                cli_overrides=cli_overrides,
            )
            from qp.strategy.config import get_strategy_config

            cfg = get_strategy_config(strategy_name)
            weights = freeze_weights if freeze_weights is not None else dict(cfg.factors)
            features = list(weights.keys())
            n_factors = len(features)
            result.metrics["score_rows"] = float(scores.height if not scores.is_empty() else 0)
        else:
            # ── Legacy: bare factor pipeline ──
            fundamental_data = None
            valuation_data = None
            try:
                index_df = self._load_index_data()
            except Exception:
                index_df = None
            logger.info("[2/6] 计算原始因子值...")
            n_factors = len(PRICE_VOLUME_FACTORS)
            weights = {f: ALL_FACTOR_DIRECTIONS.get(f, 1) / n_factors for f in PRICE_VOLUME_FACTORS}
            features = list(PRICE_VOLUME_FACTORS)
            n_pos = sum(1 for v in weights.values() if v > 0)
            n_neg = sum(1 for v in weights.values() if v < 0)
            logger.info(
                "   因子: {} 个 ({} IC+, {} IC-) / 方向校准",
                n_factors,
                n_pos,
                n_neg,
            )

            # Compute raw factors for all stocks
            all_raw: dict[str, dict[str, dict[str, float]]] = {}
            for code, df in price_data.items():
                factors = compute_all_factors(df.sort("trade_date"), index_df=index_df)
                if factors.is_empty():
                    continue
                for row in factors.iter_rows(named=True):
                    date_str = str(row["trade_date"])
                    if date_str not in all_raw:
                        all_raw[date_str] = {}
                    all_raw[date_str][code] = {
                        f: float(row[f]) for f in PRICE_VOLUME_FACTORS if f in row
                    }
            logger.info("   原始因子: {} 天截面", len(all_raw))

            # Factor pipeline (winsorize → normalize → neutralize → combine)
            logger.info("[2.5/6] 因子管线处理 (Winsorize→Normalize→Neutralize→Combine)...")
            neutralize_method = "median" if industry_neutral else None
            scores = factor_pipeline(
                all_raw,
                weights=weights,
                normalize_method="rank",
                winsorize_method="mad",
                industry_map=_build_industry_map(price_data) if industry_neutral else None,
                neutralize_method=neutralize_method,
                orthogonalize=orthogonalize,
            )
            logger.info("   得分矩阵: {} 行", scores.height)
            result.metrics["score_rows"] = float(scores.height)

        # ── Stage 3: IC analysis ──
        logger.info("[3/6] Rank IC 分析...")
        if scores.is_empty():
            logger.warning("   无数据，跳过 IC 分析")
            result.status = PipelineStatus.FAILED
            result.errors.append("No score data — check dataset")
            return result

        # Use evaluation module for full IC analysis with threshold checks
        price_flat = _flatten_price_data(price_data)
        ic_record = evaluate_factor_ic(
            scores,
            price_flat,
            forward_days=5,
            min_stocks_per_day=10,
        )
        logger.info("   {}", ic_record.summary())
        result.metrics["ic_mean"] = ic_record.ic_mean
        result.metrics["ic_ir"] = ic_record.ic_ir
        result.metrics["ic_t_stat"] = ic_record.ic_t_stat
        result.metrics["ic_positive_pct"] = ic_record.ic_positive_pct
        result.metrics["ic_mean_pass"] = float(ic_record.ic_mean_pass)
        result.metrics["ic_ir_pass"] = float(ic_record.ic_ir_pass)

        # ── Stage 3.5: Factor IC attribution ──
        logger.info("")
        logger.info("[3.5/6] 因子 IC 归因分析...")
        factor_weights = weights  # from Stage 2 (already determined)
        factor_ic_table = _compute_factor_ic_attribution(
            price_data=price_data,
            valuation_data=valuation_data,
            fundamental_data=fundamental_data,
            factor_weights=factor_weights,
            price_flat=price_flat,
            index_df=index_df,
            extra_factors=extra_factors,
        )
        if factor_ic_table:
            _log_factor_ic_table(factor_ic_table, factor_weights)
            for i, entry in enumerate(factor_ic_table[:3]):
                result.metrics[f"factor_{i + 1}_name"] = entry["factor"]
                result.metrics[f"factor_{i + 1}_ic"] = entry["ic_mean"]
                result.metrics[f"factor_{i + 1}_ic_ir"] = entry["ic_ir"]

            # ── Stage 3.6: Optimize weights from factor ICs ──
            if freeze_weights:
                logger.info("")
                logger.info("[3.6/6] 因子权重: 🔒 冻结 (复现模式)")
                optimized_weights = dict(freeze_weights)
            else:
                logger.info("")
                logger.info("[3.6/6] 因子权重优化 (IC-加权, 全量数据)...")
                optimized_weights = _optimize_weights_from_ic(factor_ic_table, factor_weights)
                _log_weight_optimization(factor_weights, optimized_weights)

            # Re-run strategy with optimized weights (skip if unchanged, ML mode, or frozen)
            _weights_changed = not freeze_weights and any(
                abs(optimized_weights.get(k, 0) - factor_weights.get(k, 0)) > 0.01
                for k in set(list(optimized_weights) + list(factor_weights))
            )
            if use_full_strategy and (_weights_changed or not model_mode):
                if model_mode:
                    logger.info("   以优化权重重新运行策略 (ML 模式跳过 — 模型自学习权重)")
                else:
                    logger.info("   以优化权重重新运行策略...")
                optimized_config = _build_optimized_config(strategy_name, optimized_weights)
                if optimized_config:
                    # For ML mode: skip the full re-run, just re-evaluate IC from existing scores
                    if model_mode:
                        ic2 = evaluate_factor_ic(
                            scores,
                            price_flat,
                            forward_days=5,
                            min_stocks_per_day=10,
                        )
                        logger.info(
                            "   优化后复合 IC: {:+.4f} | IR: {:.2f} | IC>0: {:.0f}% (ML 复用原始评分)",
                            ic2.ic_mean,
                            ic2.ic_ir,
                            ic2.ic_positive_pct,
                        )
                        result.metrics["ic_mean_optimized"] = ic2.ic_mean
                        result.metrics["ic_ir_optimized"] = ic2.ic_ir
                        result.metadata["optimized_weights"] = "ml_skip"
                    else:
                        _sig2, scores2, *_rest = self._run_full_strategy(
                            price_data=price_data,
                            top_n=top_n,
                            rebalance_freq=rebalance_freq,
                            sell_buffer=sell_buffer,
                            strategy_name=strategy_name,
                            model_mode=model_mode,
                            config_override=optimized_config,
                            score_band=score_band,
                            cli_overrides=cli_overrides,
                        )
                        ic2 = evaluate_factor_ic(
                            scores2 if not scores2.is_empty() else scores,
                            price_flat,
                            forward_days=5,
                            min_stocks_per_day=10,
                        )
                        logger.info(
                            "   优化后复合 IC: {:+.4f} | IR: {:.2f} | IC>0: {:.0f}% (之前 IC={:+.4f})",
                            ic2.ic_mean,
                            ic2.ic_ir,
                            ic2.ic_positive_pct,
                            ic_record.ic_mean,
                        )
                        result.metrics["ic_mean_optimized"] = ic2.ic_mean
                        result.metrics["ic_ir_optimized"] = ic2.ic_ir
                        result.metadata["optimized_weights"] = ",".join(
                            f"{k}={v:+.3f}" for k, v in sorted(optimized_weights.items())
                        )
                        scores = scores2 if not scores2.is_empty() else scores
                        weights = optimized_weights
            logger.info("")

        # Layered test for monotonicity validation
        layered = compute_layered_returns(
            scores,
            price_flat,
            n_quantiles=5,
            forward_days=5,
            min_stocks_per_day=50,
        )
        logger.info("   {}", layered.summary())
        # Per-quantile detail for debugging monotonicity
        if layered.quantile_returns:
            qs = sorted(layered.quantile_returns.keys())
            q_str = "  ".join(f"Q{q}={layered.quantile_returns[q]:+.4f}" for q in qs)
            logger.info("   分位数收益: {}", q_str)
        result.metrics["top_bottom_spread"] = layered.top_bottom_spread
        result.metrics["spread_t_stat"] = layered.spread_t_stat
        result.metrics["monotonicity_t_stat"] = layered.monotonicity_t_stat
        result.metrics["is_monotonic"] = float(layered.is_monotonic)
        result.metrics["direction_correct"] = float(layered.direction_correct)

        # ── Diagnostic: Q1-Q5 特征画像 ──
        _diagnose_quintile_profiles(scores, price_data, logger)

        # ── IC Gate (§10.1 — 强制) ──
        # Per rule.md §10.1: "未同时满足以上条件的因子，只能进入
        # Research Debt Archive，不允许进入 Strategy 层"
        # Gate: top-bottom spread must be significant AND direction-correct.
        # Monotonicity (Spearman rho) is a soft diagnostic, not a hard gate —
        # middle quantile inversion doesn't prevent top-bottom separation.
        layered_pass = layered.direction_correct and layered.spread_t_stat >= 2.0
        ic_pass = ic_record.all_pass
        gate_passed = layered_pass and ic_pass

        if not gate_passed and not skip_gate:
            # Build detailed failure report
            failures: list[str] = []
            if not ic_record.ic_mean_pass:
                failures.append(f"|IC|={abs(ic_record.ic_mean):.4f} < 0.02 (阈值)")
            if not ic_record.ic_ir_pass:
                failures.append(f"IC_IR={ic_record.ic_ir:.2f} < 0.3 (阈值)")
            if not ic_record.ic_t_stat_pass:
                failures.append(f"IC t-stat={ic_record.ic_t_stat:.2f} < 2.0 (阈值)")
            if not layered.is_monotonic:
                if not layered.direction_correct:
                    failures.append(
                        f"因子方向反转: 高分→低收益 (Q5-Q1={layered.top_bottom_spread:+.4f})，"
                        "无法用于做多策略"
                    )
                else:
                    # Soft warning — top-bottom still works even if middle isn't monotonic
                    logger.warning(
                        "   ⚠ 分层收益不单调 (rho={:.2f}) — 但 direction_correct=True, spread 依然可用",
                        layered.monotonicity_t_stat,
                    )
            if layered.spread_t_stat < 2.0:
                failures.append(f"Q5-Q1 spread t={layered.spread_t_stat:.2f} < 2.0 (阈值)")

            logger.error("   ⛔ 因子检验未通过 §10.1 — 禁止进入策略层")
            for f in failures:
                logger.error("      ❌ {}", f)
            logger.error("")
            logger.error("   规则: rule.md §10.1 — 不满足条件的因子只能存档到")
            logger.error("   Research Debt Archive，不允许进入回测。")
            logger.error("   若确认要跳过门禁（仅限探索），使用 --skip-gate。")

            # ── Build GateResult and archive to Research Debt ──
            from qp.shared.types import ValidationStatus
            from qp.validation.result import GateDecision, GateResult, RuleResult

            gate_rules: list[RuleResult] = []
            gate_rules.append(
                RuleResult(
                    "rank_ic",
                    ValidationStatus.PASS if ic_record.ic_mean_pass else ValidationStatus.FAIL,
                    80 if ic_record.ic_mean_pass else 30,
                    threshold=0.02,
                    actual_value=abs(ic_record.ic_mean),
                    detail=f"|IC|={abs(ic_record.ic_mean):.4f}",
                )
            )
            gate_rules.append(
                RuleResult(
                    "ic_ir",
                    ValidationStatus.PASS if ic_record.ic_ir_pass else ValidationStatus.FAIL,
                    80 if ic_record.ic_ir_pass else 30,
                    threshold=0.3,
                    actual_value=ic_record.ic_ir,
                    detail=f"IC_IR={ic_record.ic_ir:.2f}",
                )
            )
            gate_rules.append(
                RuleResult(
                    "ic_t_stat",
                    ValidationStatus.PASS if ic_record.ic_t_stat_pass else ValidationStatus.FAIL,
                    80 if ic_record.ic_t_stat_pass else 30,
                    threshold=2.0,
                    actual_value=ic_record.ic_t_stat,
                    detail=f"t={ic_record.ic_t_stat:.2f}",
                )
            )
            gate_rules.append(
                RuleResult(
                    "monotonicity",
                    ValidationStatus.PASS if layered.is_monotonic else ValidationStatus.FAIL,
                    80 if layered.is_monotonic else 30,
                    threshold=2.0,
                    actual_value=layered.monotonicity_t_stat,
                    detail=f"monotonicity t={layered.monotonicity_t_stat:.2f}",
                )
            )
            gate_rules.append(
                RuleResult(
                    "spread",
                    ValidationStatus.PASS
                    if layered.spread_t_stat >= 2.0
                    else ValidationStatus.FAIL,
                    80 if layered.spread_t_stat >= 2.0 else 30,
                    threshold=2.0,
                    actual_value=layered.spread_t_stat,
                    detail=f"Q5-Q1 spread t={layered.spread_t_stat:.2f}",
                )
            )

            gate = GateResult(
                strategy_id=strategy_name,
                stage="backtest_passed",
                decision=GateDecision.RESEARCH_ONLY
                if (ic_pass and not layered_pass)
                else GateDecision.BLOCKED,
                score=sum(r.score for r in gate_rules) / len(gate_rules),
                confidence=sum(1 for r in gate_rules if r.status == ValidationStatus.PASS)
                / len(gate_rules),
                data_integrity="PASS",
                factor_validity="PASS" if ic_pass else "FAIL",
                portfolio_conversion="PASS" if layered_pass else "FAIL",
                rules=gate_rules,
                recommendation=(
                    f"策略 {strategy_name} 具有统计预测力 (IC={ic_record.ic_mean:+.4f}, "
                    f"IR={ic_record.ic_ir:.2f}) 但分层收益不单调 (t={layered.monotonicity_t_stat:.2f})。"
                    f"建议: 研究 Q5 顶部塌陷原因或重新定义因子。"
                )
                if (ic_pass and not layered_pass)
                else (
                    f"策略 {strategy_name} 因子检验未通过。建议: 检查因子计算、数据源、"
                    f"或缩减因子数量。"
                ),
            )

            # Archive to Research Debt with structured GateResult
            debt_id = _archive_research_debt(
                strategy_name=strategy_name,
                ic_record=ic_record,
                layered=layered,
                failures=failures,
                start=start_date_str,
                end=end_date_str,
                gate_result=gate,
            )
            gate.artifacts.append(f"data/knowledge/research_debt/{debt_id}.md")

            # Persist GateResult JSON
            from pathlib import Path

            gate_dir = Path("data/experiments")
            gate_dir.mkdir(parents=True, exist_ok=True)
            gate_file = (
                gate_dir / f"{strategy_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_gate.json"
            )
            import json as _json

            gate_file.write_text(
                _json.dumps(gate.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            gate.artifacts.append(str(gate_file))

            result.status = PipelineStatus.FAILED
            result.errors.append(
                f"§10.1 Gate: {len(failures)} threshold(s) not met — " + "; ".join(failures)
            )
            result.metadata["gate_result"] = gate.to_dict()  # type: ignore[assignment]
            result.metadata["gate_failures"] = "; ".join(failures)
            return result

        if not ic_pass:
            logger.warning(
                "   ⚠ IC 指标偏弱 (|IC|={:.4f}, IR={:.2f}) — 分层检验已通过，继续回测",
                abs(ic_record.ic_mean),
                ic_record.ic_ir,
            )

        # ── Stage 4: Signal generation (legacy path only) ──
        if not use_full_strategy:
            logger.info("[4/6] 生成调仓信号...")
            n_before = scores.height
            scores = scores.filter(pl.col("score") != 0.0)
            n_zero = n_before - scores.height
            if n_zero > 0:
                logger.info("   过滤 score=0: {} 行 (数据不足)", n_zero)
            signals = generate_rebalance_signals(
                scores,
                top_n=top_n,
                rebalance_freq=rebalance_freq,
                sell_buffer_rank=sell_buffer,
            )
        else:
            logger.info("[4/6] 调仓信号 (策略引擎已生成)...")

        if not signals.is_empty():
            buys_n = signals.filter(pl.col("signal") == "buy").height
            sells_n = signals.filter(pl.col("signal") == "sell").height
            rebalance_days = signals["date"].n_unique()
            logger.info(
                "   买入信号: {} 条 | 卖出信号: {} 条 | 调仓日: {} 天",
                buys_n,
                sells_n,
                rebalance_days,
            )
            result.metrics["buy_signals"] = float(buys_n)
            result.metrics["sell_signals"] = float(sells_n)

            # Latest rebalance
            latest_date = signals["date"].max()
            latest = signals.filter(pl.col("date") == latest_date).sort("signal", descending=True)
            for row in latest.iter_rows(named=True):
                emoji = "🟢" if row["signal"] == "buy" else "🔴"
                logger.info(
                    "     {} {:4s}  {:8s}  score={:.4f}",
                    emoji,
                    row["signal"],
                    row["symbol"],
                    row["score"],
                )
        else:
            logger.warning("   无信号生成")
            result.metrics["buy_signals"] = 0.0
            result.metrics["sell_signals"] = 0.0

        # ── Stage 5: Backtest (Layer 7 SimulatedBroker) ──
        logger.info("[5/6] 回测 (SimulatedBroker, 信号日调仓)...")
        bt = self._compute_backtest(signals, price_data, scores=scores, top_n=top_n)
        logger.info("   总收益:    {:+.2f}%", bt["total_return_pct"])
        logger.info("   年化夏普:  {:.2f}", bt["sharpe"])
        logger.info("   最大回撤:  {:.2f}%", bt["max_dd_pct"])
        logger.info("   期末资产:  ¥{:,.0f}", bt["final_equity"])
        logger.info(
            "   交易次数:  {} (止损触发: {})",
            bt["n_trades"],
            bt.get("stop_loss_hits", 0),
        )
        logger.info("   总成本:    ¥{:,.0f} (佣金+印花税+滑点)", bt["total_cost"])
        if bt.get("turnover_pct", 0) > 0:
            logger.info("   累计换手:  {:.0f}% (总卖出/平均权益)", bt["turnover_pct"])
        result.metrics["total_return_pct"] = bt["total_return_pct"]
        result.metrics["sharpe"] = bt["sharpe"]
        result.metrics["max_dd_pct"] = bt["max_dd_pct"]
        result.metrics["final_equity"] = bt["final_equity"]
        result.metrics["n_trading_days"] = float(bt["n_trading_days"])
        result.metrics["n_trades"] = float(bt["n_trades"])
        result.metrics["total_cost"] = bt["total_cost"]
        result.metrics["turnover_pct"] = bt.get("turnover_pct", 0.0)
        result.metrics["stop_loss_hits"] = float(bt.get("stop_loss_hits", 0))
        result.metrics["risk_exit_hits"] = float(bt.get("risk_exit_hits", 0))

        # ── Stage 6: Benchmark ──
        logger.info("[6/6] 基准对比 (等权持有)...")
        bench_ret = self._benchmark_return(price_data, symbols, start_date_str, end_date_str)
        logger.info("   等权买入持有: {:+.2f}%", bench_ret)
        result.metrics["benchmark_return_pct"] = bench_ret

        excess = bt["total_return_pct"] - bench_ret
        logger.info("   超额收益:    {:+.2f}%", excess)
        result.metrics["excess_return_pct"] = excess

        # ── Score Band auto-search (when --score-band auto) ──
        if score_band == "auto" and use_full_strategy and not scores.is_empty():
            from qp.strategy.config import get_strategy_config as _get_scfg

            _auto_search_score_band(scores, price_flat, _get_scfg(strategy_name))

        logger.info("=" * 70)
        status_text = "策略跑赢基准 ✅" if excess > 0 else "策略跑输基准 ❌"
        logger.info("实验完成 — {} (超额: {:+.2f}%)", status_text, excess)
        logger.info("=" * 70)

        # ── Auto-record experiment (Rule 6: Everything is Experiment) ──
        # Generate ID early so we can snapshot data before recording
        from pathlib import Path as _Path

        experiment_id = f"multifactor_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        # ── Data Snapshot: pin filtered price data for reproducibility ──
        snapshot_dir = _Path("data/experiments") / experiment_id
        try:
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            # Save full price data (not just close) so experiment can be reproduced
            full_parts: list[pl.DataFrame] = []
            for _code, _df in price_data.items():
                if _df is not None and not _df.is_empty() and "trade_date" in _df.columns:
                    full_parts.append(_df)
            if full_parts:
                snapshot_df = pl.concat(full_parts)
                snapshot_df.write_parquet(str(snapshot_dir / "price_data.parquet"))

            # Save daily NAV (equity curve) for WebUI charting
            daily_equity_list = bt.get("daily_equity", [])
            daily_dates = bt.get("daily_dates", [])
            daily_benchmark_list = bt.get("daily_benchmark", [])
            daily_drawdown_list = bt.get("daily_drawdown", [])
            daily_return_pct_list = bt.get("daily_return_pct", [])
            if daily_equity_list and daily_dates and len(daily_equity_list) == len(daily_dates):
                n_rows = len(daily_dates)
                nav_df = pl.DataFrame(
                    {
                        "date": daily_dates,
                        "portfolio_value": pl.Series(
                            [round(e, 2) for e in daily_equity_list], dtype=pl.Float64
                        ),
                        "benchmark_value": pl.Series(
                            [round(b, 2) for b in daily_benchmark_list]
                            if len(daily_benchmark_list) == n_rows
                            else [0.0] * n_rows,
                            dtype=pl.Float64,
                        ),
                        "daily_return": pl.Series(
                            daily_return_pct_list
                            if len(daily_return_pct_list) == n_rows
                            else [0.0] * n_rows,
                            dtype=pl.Float64,
                        ),
                        "drawdown": pl.Series(
                            daily_drawdown_list
                            if len(daily_drawdown_list) == n_rows
                            else [0.0] * n_rows,
                            dtype=pl.Float64,
                        ),
                    }
                )
                nav_df.write_parquet(str(snapshot_dir / "daily_nav.parquet"))
                logger.info("📈 每日净值已保存: {} 行", nav_df.height)

            # Save trade log for WebUI trade detail
            trade_log_df = bt.get("trade_log")
            if trade_log_df is not None and not trade_log_df.is_empty():
                trade_log_df.write_parquet(str(snapshot_dir / "trade_log.parquet"))
                logger.info("📋 交易日志已保存: {} 笔", trade_log_df.height)

            logger.info("📸 数据快照已保存: {}", snapshot_dir)
        except Exception as _exc:
            logger.warning("数据快照保存失败 (非致命): {}", _exc)

        self._record_experiment(
            result=result,
            start_date=start_date_str,
            end_date=end_date_str,
            dataset=dataset,
            experiment_id=experiment_id,
            strategy_name=strategy_name,
            features=features,
            weights=weights,
            top_n=top_n,
            rebalance_freq=rebalance_freq,
            industry_neutral=industry_neutral,
            orthogonalize=orthogonalize,
        )

        # ── Auto-register strategy with backtest metrics (ADR-031) ──
        # When Gate passes and backtest completes, write weights + metrics
        # to StrategyRegistry so Daily Pipeline can discover it automatically.
        # Skip if running in resume/reproduce mode (freeze_weights set).
        if gate_passed and not freeze_weights:
            try:
                from qp.strategy.config import get_strategy_config
                from qp.strategy.registry import StrategyMeta, StrategyRegistry

                registry = StrategyRegistry()
                cfg = get_strategy_config(strategy_name)

                meta = StrategyMeta(
                    weights=dict(cfg.factors),
                    parameters={
                        "top_n": top_n,
                        "rebalance": rebalance_freq,
                        "industry_neutral": cfg.industry_neutral,
                        "orthogonalize": cfg.orthogonalize,
                        "anti_chase": cfg.anti_chase,
                    },
                    backtest_ic=float(ic_record.ic_mean),
                    backtest_sharpe=float(bt.get("sharpe", 0)),
                    backtest_max_dd=float(bt.get("max_dd_pct", 0)),
                    backtest_excess_return=float(excess),
                    owner="experiment",
                    strategy_version=datetime.now().strftime("v%Y%m%d"),
                )

                # Update metadata if strategy exists, otherwise just save
                # (strategy instance may not be registered yet — that's ok,
                #  Daily Pipeline will register it with from_today_scores)
                #
                # ⚠️ Production-state guard (2026-08-14): experiments must NOT
                # overwrite the meta of strategies that have left RESEARCH —
                # a backtest run (even a worse control group) used to silently
                # replace the approved strategy's meta (weights / backtest_* /
                # orthogonalize) in the registry. Full experiment results are
                # already persisted in data/experiments/*.json; registry meta
                # stays as the production snapshot. Only RESEARCH-lifecycle
                # strategies get auto-updated by experiments.
                _lifecycle = (
                    registry.get_lifecycle(strategy_name)
                    if strategy_name in registry.list_strategies()
                    else None
                )
                if _lifecycle is not None and _lifecycle != StrategyLifecycle.RESEARCH:
                    logger.info(
                        "🔒 实验不覆盖注册表 meta（策略 {} 生命周期={}，非 RESEARCH）",
                        strategy_name,
                        _lifecycle.value,
                    )
                elif strategy_name in registry.list_strategies():
                    registry.set_meta(strategy_name, meta)
                else:
                    # Register metadata-only entry for cross-process persistence
                    registry._metadata[strategy_name] = meta
                    registry._lifecycles[strategy_name] = StrategyLifecycle.RESEARCH
                    registry._save()

                logger.info(
                    "📋 策略权重+回测指标已写入 Registry: {} (IC={:.4f}, Sharpe={:.2f})",
                    strategy_name,
                    meta.backtest_ic,
                    meta.backtest_sharpe,
                )
            except Exception as exc:
                logger.debug("自动写入 Registry 跳过: {}", exc)

        return result

    # ------------------------------------------------------------------
    # Full strategy runner
    # ------------------------------------------------------------------

    def _run_full_strategy(
        self,
        price_data: dict[str, pl.DataFrame],
        top_n: int,
        rebalance_freq: int,
        sell_buffer: int,
        strategy_name: str,
        model_mode: bool = False,
        config_override: StrategyConfig | None = None,
        score_band: str | None = None,
        cli_overrides: dict[str, Any] | None = None,
    ) -> tuple[pl.DataFrame, pl.DataFrame, dict, dict, pl.DataFrame, dict | None]:
        """Run the momentum_vol_full strategy through the strategy layer.

        Args:
            config_override: If provided, use this config instead of the default.

        Returns:
            (signals, scores, fundamental_data, valuation_data, index_df).
        """
        from qp.strategy.config import get_strategy_config
        from qp.strategy.strategies.momentum_vol_full import run_momentum_vol_full

        # Strategy → run function dispatch
        _STRATEGY_RUNNERS: dict[str, Any] = {
            "alpha_multi_factor_v1": None,  # lazy import below
        }

        def _get_runner(name: str):
            if name == "alpha_multi_factor_v1":
                from qp.strategy.strategies.alpha_multi_factor import (
                    run_alpha_multi_factor_v1,
                )

                return run_alpha_multi_factor_v1
            if name == "alpha_multi_factor_v2":
                from qp.strategy.strategies.alpha_multi_factor import (
                    run_alpha_multi_factor_v2,
                )

                return run_alpha_multi_factor_v2
            if name == "alpha_ensemble_v2":
                import qp.strategy.strategies.ensemble_v2

                return run_momentum_vol_full
            if name == "alpha_ensemble_v3":
                import qp.strategy.strategies.ensemble_v3  # noqa: F401 — registers config

                return run_momentum_vol_full
            return run_momentum_vol_full

        run_func = _get_runner(strategy_name)

        if config_override is not None:
            config = config_override
        else:
            config = get_strategy_config(strategy_name)
        # Always work on a private copy — never mutate the registered config
        # object shared across sessions/experiments.
        config = config.with_overrides()

        # Apply CLI experiment overrides onto the copy (never mutate the
        # registered config — get_strategy_config returns the shared object).
        if cli_overrides:
            config = config.with_overrides(**cli_overrides)
            logger.info(
                "   配置覆盖: {}",
                dict(cli_overrides),
            )

        # Positional CLI params always apply (top_n / rebalance / model_mode)
        config.max_positions = top_n
        config.rebalance_freq = rebalance_freq
        config.sell_buffer_multiplier = max(1, sell_buffer // top_n) if top_n > 0 else 2
        config.model_mode = model_mode

        # Load CSI300 index data for market filter + regime detection
        index_df = self._load_index_data()

        # Load fundamental data for quality filter
        fundamental_data = self._load_fundamental_data()
        n_fund = len(fundamental_data)

        # Load capital flow data (主力净流入) — available for flow features
        capital_flow_data = self._load_capital_flow_data()
        n_flow = len(capital_flow_data)
        if n_flow > 0:
            logger.info("资金流数据可用: {} 只股票 (可接资金流特征/过滤)", n_flow)

        # Load valuation data (PE_TTM, PB, PCF_OCF from EPS/NAV + close)
        valuation_data = self._load_valuation_data(
            symbols=list(price_data.keys()),
            price_data=price_data,
        )
        n_val = len(valuation_data)

        logger.info("[2/6] 策略引擎 — {} 完整版...", config.display_name or config.name)
        logger.info(
            "   因子: {} 个 | 质量过滤: ✅ ({}只有基本面) | "
            "估值: ✅ ({}只有估值) | 行业中性: ✅ | "
            "正交化: ✅ | 防追高: ✅ | 卖出缓冲: {}",
            len(config.factors),
            n_fund,
            n_val,
            config.get_sell_buffer_rank(),
        )

        # Run full strategy pipeline for signals + scores (with all filters)
        extra_overrides: dict[str, Any] = {}

        # ── Regime detection (for Factor Layer v2 ensemble) ──
        detected_regime = ""
        if getattr(config, "use_regime_ensemble", False) and index_df is not None:
            try:
                from qp.strategy.market_regime import MarketRegimeDetector

                detector = MarketRegimeDetector()
                regime_result = detector.detect(index_df, price_data)
                detected_regime = regime_result.regime
                logger.info(
                    "   市场状态: {} (置信度: {:.0%})",
                    detected_regime,
                    regime_result.confidence,
                )
                extra_overrides["regime"] = detected_regime
            except Exception:
                pass

        if score_band:
            parts = score_band.split("-")
            if len(parts) == 2:
                extra_overrides["score_percentile_min"] = float(parts[0])
                extra_overrides["score_percentile_max"] = float(parts[1])
                logger.info(
                    "   🎯 Score band: {:.0f}%-{:.0f}% (Q{:.0f} region)",
                    float(parts[0]),
                    float(parts[1]),
                    float(parts[0]) / 20 + 1,
                )
        strategy_result = run_func(
            price_data=price_data,
            config=config,
            index_df=index_df,
            fundamental_data=fundamental_data,
            valuation_data=valuation_data,
            **extra_overrides,
        )

        if isinstance(strategy_result, tuple):
            signals, extra = strategy_result
            scores = extra.get("scores") if isinstance(extra, dict) else None  # type: ignore[union-attr]
            extra_factors = extra.get("extra_factors") if isinstance(extra, dict) else None
        else:
            signals = strategy_result  # type: ignore[assignment]
            scores = None
            extra_factors = None

        if scores is None:
            logger.warning("策略未返回截面得分，IC 分析将跳过")

        return (
            signals,
            scores,
            fundamental_data,
            valuation_data,
            index_df,
            extra_factors,
        )  # type: ignore[return-value]

    @staticmethod
    def _load_fundamental_data() -> dict[str, pl.DataFrame]:
        """Load fundamental data for quality filter from local parquet.

        Reads ``data/dataset/fundamentals_latest.parquet`` produced by
        FundamentalPipeline (``qp ingest fundamental``, source: AkShare
        via FundamentalAdapter). Returns {code: DataFrame(report_date,
        publish_date, ROE, gross_margin, ...)} — empty dict if the
        file is missing (quality filter skipped gracefully).
        """
        path = Path("data/dataset/fundamentals_latest.parquet")
        if not path.exists():
            logger.info(
                "基本面 parquet 不存在 ({}) — 质量过滤跳过。先运行 `qp ingest fundamental`",
                path,
            )
            return {}

        try:
            raw = pl.read_parquet(path)
        except Exception as e:
            logger.warning("基本面 parquet 读取失败 ({}): 质量过滤跳过", e)
            return {}

        if raw.is_empty() or "symbol" not in raw.columns:
            return {}

        result: dict[str, pl.DataFrame] = {}
        for code, group in raw.group_by("symbol"):
            symbol = str(code[0])
            df = group.drop("symbol").sort("report_date")
            result[symbol] = df
        logger.info("📊 基本面数据: {} 只股票 (质量过滤启用)", len(result))
        return result

    @staticmethod
    def _load_capital_flow_data() -> dict[str, pl.DataFrame]:
        """Load capital flow data (主力净流入/北向持股) from local parquet.

        Reads ``data/dataset/capital_flow_latest.parquet`` produced by
        CapitalFlowPipeline (``qp ingest capital-flow``, source: AkShare).
        Returns {code: DataFrame(date, main_net_flow, ...)} — empty dict if
        the file is missing (downstream flow features skip gracefully).
        """
        path = Path("data/dataset/capital_flow_latest.parquet")
        if not path.exists():
            logger.info(
                "资金流 parquet 不存在 ({}) — 资金流特征跳过。先运行 `qp ingest capital-flow`",
                path,
            )
            return {}

        try:
            raw = pl.read_parquet(path)
        except Exception as e:
            logger.warning("资金流 parquet 读取失败 ({}): 资金流特征跳过", e)
            return {}

        if raw.is_empty() or "symbol" not in raw.columns:
            return {}

        result: dict[str, pl.DataFrame] = {}
        for code, group in raw.group_by("symbol"):
            symbol = str(code[0])
            df = group.drop("symbol").sort("date")
            result[symbol] = df
        logger.info("💰 资金流数据: {} 只股票", len(result))
        return result

    @staticmethod
    def _load_valuation_data(
        symbols: list[str],
        price_data: dict[str, pl.DataFrame],
    ) -> dict[str, pl.DataFrame]:
        """Load valuation data (PE_TTM, PB, PCF_OCF) from fundamentals + close.

        Computed PIT-compliant via qp.data.valuation.product.compute_valuation
        (publish_date <= trade_date), using the local fundamentals parquet.
        Returns {symbol: DataFrame(trade_date, PE_TTM, PB, PCF_OCF)}.
        """
        from qp.data.valuation.product import compute_valuation

        path = Path("data/dataset/fundamentals_latest.parquet")
        if not path.exists():
            return {}

        try:
            raw = pl.read_parquet(path)
        except Exception:
            return {}

        if raw.is_empty() or "symbol" not in raw.columns:
            return {}

        # Group fundamentals by symbol
        fund_by_symbol: dict[str, pl.DataFrame] = {}
        for code, group in raw.group_by("symbol"):
            fund_by_symbol[str(code[0])] = group.drop("symbol").sort("report_date")

        result: dict[str, pl.DataFrame] = {}
        for sym in symbols:
            fund_df = fund_by_symbol.get(sym)
            price_df = price_data.get(sym)
            if fund_df is None or price_df is None or price_df.is_empty():
                continue
            val = compute_valuation(sym, price_df, fund_df)
            if val is not None and not val.is_empty():
                result[sym] = val

        if result:
            logger.info("💰 估值数据: {} 只股票 (PE/PB 过滤启用)", len(result))
        return result

    def _load_index_data(self) -> pl.DataFrame | None:
        """Load CSI300 index data for market filter / regime detection.

        Reads the local Gold dataset (data/dataset/index_csi300.parquet,
        produced by ``qp data index``). If the file is missing, attempts a
        one-time AkShare fetch (lazy network fallback); returns None only
        when both fail (market filter / regime detection skipped).
        """
        from qp.data.dataset.index_provider import (
            fetch_index_data,
            load_index_data,
        )

        # Try local Gold dataset first; if missing, one-time network fetch.
        local = load_index_data()
        if local is not None:
            return local

        logger.info("指数数据缺失，尝试拉取...")
        try:
            fetch_index_data(force=False)
            return load_index_data()
        except Exception as exc:
            logger.warning("指数拉取失败（市场过滤跳过）: {}", exc)
            return None

    @staticmethod
    def _load_snapshot(
        snapshot_path: str,
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict[str, pl.DataFrame]:
        """Load price data from an experiment snapshot parquet file.

        Behaves identically to _fetch_data but reads from a pinned snapshot
        instead of the gold dataset registry — enabling exact experiment reproduction.
        """
        from pathlib import Path

        snap = Path(snapshot_path)
        if not snap.exists():
            raise FileNotFoundError(f"快照文件不存在: {snapshot_path}")

        df_all = pl.read_parquet(str(snap))

        # Filter date range
        df_all = df_all.filter(
            (pl.col("trade_date").cast(pl.Utf8) >= start)
            & (pl.col("trade_date").cast(pl.Utf8) <= end)
        )

        # Filter symbols if specified
        if symbols:
            symbol_set = set(symbols)
            df_all = df_all.filter(pl.col("symbol").is_in(symbol_set))

        if df_all.is_empty():
            return {}

        dfs: dict[str, pl.DataFrame] = {}
        for (code,), group in df_all.group_by("symbol"):
            dfs[str(code)] = group.sort("trade_date")

        logger.info("    ✅ 快照: {} 只, {} 行", len(dfs), df_all.height)
        return dfs

    @staticmethod
    def _fetch_data(
        symbols: list[str],
        start: str,
        end: str,
        dataset: str = "daily_price_main",
        max_stocks: int = 0,
    ) -> dict[str, pl.DataFrame]:
        """Load from Gold dataset (CLAUDE.md: consumers read from Registry or parquet).

        The Gold tier is already ETL-cleaned, Contract-validated, and
        Universe-filtered. No additional processing needed.

        Args:
            symbols: explicit symbol list (empty = all stocks in dataset)
            start: start date (inclusive)
            end: end date (inclusive)
            dataset: Gold dataset name
            max_stocks: random-sample N stocks to bound memory (0 = all).
                Deterministic via DEFAULT_SEED so experiments are reproducible.
        """

        # Resolve Gold path: try DatasetRegistry first, fallback to glob latest parquet
        gold_path = ""
        registry = DatasetRegistry(base_dir="data/dataset")
        try:
            entry = registry.resolve(dataset, require_exists=True)
            gold_path = entry["path"]
            logger.info("    📂 Gold (Registry): {} (v{})", dataset, entry["version"])
        except KeyError:
            from pathlib import Path as _Path

            # Fallback 1: "daily_price_latest" → "daily_price" @ "latest"
            if dataset.endswith("_latest"):
                base_name = dataset[: -len("_latest")]
                try:
                    entry = registry.resolve(base_name, version="latest", require_exists=True)
                    gold_path = entry["path"]
                    logger.info(
                        "    📂 Gold (Registry→latest): {} → {}@latest",
                        dataset,
                        base_name,
                    )
                except KeyError:
                    pass

            # Fallback 2: direct file search
            if not gold_path:
                pattern = f"data/dataset/{dataset}_*.parquet"
                candidates = sorted(_Path().glob(pattern), reverse=True)
                # Also check exact match without version suffix (e.g. daily_price_latest.parquet)
                exact_path = _Path(f"data/dataset/{dataset}.parquet")
                if exact_path.exists():
                    candidates.insert(0, exact_path)
                for candidate in candidates:
                    if candidate.exists():
                        gold_path = str(candidate)
                        logger.info("    📂 Gold (direct): {}", candidate.name)
                        break
                else:
                    logger.error(
                        "Gold 数据集未找到。请先运行 qp data fetch (glob pattern: {})",
                        pattern,
                    )
                    return {}

        df_all = pl.read_parquet(gold_path)

        # Filter date range
        df_all = df_all.filter(
            (pl.col("trade_date").cast(pl.Utf8) >= start)
            & (pl.col("trade_date").cast(pl.Utf8) <= end)
        )

        # Filter symbols if specified
        if symbols:
            symbol_set = set(symbols)
            df_all = df_all.filter(pl.col("symbol").is_in(symbol_set))

        # Random-sample N stocks to bound memory (deterministic via DEFAULT_SEED)
        if max_stocks > 0:
            from qp.shared.constants.seed import DEFAULT_SEED

            unique_symbols = df_all["symbol"].unique().to_list()
            if len(unique_symbols) > max_stocks:
                import random

                rng = random.Random(DEFAULT_SEED)  # noqa: S311 — 抽样非加密用途，seed 固定保证可复现
                sample_codes = rng.sample(sorted(unique_symbols), max_stocks)
                df_all = df_all.filter(pl.col("symbol").is_in(sample_codes))
                logger.info(
                    "    🎲 抽样 {} 只 (共 {} 只, seed={}) 控制内存",
                    max_stocks,
                    len(unique_symbols),
                    DEFAULT_SEED,
                )

        if df_all.is_empty():
            logger.warning("    数据为空")
            return {}

        # Organize by symbol
        dfs: dict[str, pl.DataFrame] = {}
        for (code,), group in df_all.group_by("symbol"):
            dfs[str(code)] = group.sort("trade_date")

        logger.info("    ✅ {} 只, {} 行 (已清洗/校验/过滤)", len(dfs), df_all.height)
        return dfs

    @staticmethod
    def _compute_backtest(
        signals: pl.DataFrame,
        price_data: dict[str, pl.DataFrame],
        initial_capital: float = 100_000,
        scores: pl.DataFrame | None = None,
        top_n: int = 10,
    ) -> dict[str, Any]:
        """Broker-based backtest via Layer 7 SimulatedBroker.

        On each trading day: mark positions to market via broker.set_prices().
        On rebalance days: compute target portfolio from scores, sell stocks
        not in target, buy new entries with equal-weight allocation.

        Uses SimulatedBroker for realistic execution with slippage and cost
        tracking, replacing the previous hand-rolled dict loop (ADR-029).
        """
        from qp.portfolio.risk_exit import RiskExitConfig, RiskExitManager, TradeReason
        from qp.simulation.broker import SimulatedBroker

        _empty_curve: list[float] = []
        _empty_dates: list[str] = []
        if signals.is_empty():
            return {
                "total_return_pct": 0.0,
                "sharpe": 0.0,
                "max_dd_pct": 0.0,
                "final_equity": initial_capital,
                "n_trading_days": 0,
                "n_trades": 0,
                "total_cost": 0.0,
                "stop_loss_hits": 0,
                "turnover_pct": 0.0,
                "daily_equity": _empty_curve,
                "daily_dates": _empty_dates,
                "daily_benchmark": _empty_curve,
                "daily_drawdown": _empty_curve,
                "daily_return_pct": _empty_curve,
            }

        broker = SimulatedBroker(initial_cash=initial_capital)
        risk_mgr = RiskExitManager(RiskExitConfig(stop_loss_pct=-0.10))

        # Build flat price DataFrame with volume for ADV
        all_prices = _flatten_price_data_for_backtest(price_data)
        if all_prices.is_empty():
            return {
                "total_return_pct": 0.0,
                "sharpe": 0.0,
                "max_dd_pct": 0.0,
                "final_equity": initial_capital,
                "n_trading_days": 0,
                "n_trades": 0,
                "total_cost": 0.0,
                "stop_loss_hits": 0,
                "turnover_pct": 0.0,
                "daily_equity": _empty_curve,
                "daily_dates": _empty_dates,
                "daily_benchmark": _empty_curve,
                "daily_drawdown": _empty_curve,
                "daily_return_pct": _empty_curve,
            }

        # Build stock name map (ST detection)
        name_map: dict[str, str] = {}
        for code, df in price_data.items():
            if df is not None and "name" in df.columns and not df.is_empty():
                name_map[str(code)] = str(df["name"].tail(1).item())

        all_dates = sorted(all_prices["trade_date"].unique().to_list())
        daily_equity: list[float] = []
        daily_benchmark: list[float] = []

        # ── Benchmark baseline: equal-weight all-stocks buy-and-hold ──
        base_avg_close = 0.0
        if all_dates:
            first_day_df = all_prices.filter(pl.col("trade_date") == all_dates[0])
            if not first_day_df.is_empty():
                first_close = first_day_df["close"]
                first_close_filtered = first_close.filter(first_close >= 1.0)
                use_close = first_close_filtered if len(first_close_filtered) > 100 else first_close
                base_avg_close = float(use_close.median())  # type: ignore[arg-type]  # polars median 类型推断噪音
        if base_avg_close <= 0:
            base_avg_close = 1.0

        total_trades = 0
        total_buy_value: float = 0.0
        total_sell_value: float = 0.0
        stop_loss_hits = 0
        risk_exit_hits = 0
        min_equity = initial_capital
        min_date = str(all_dates[0]) if all_dates else ""
        rebalance_freq = 20  # match generate_rebalance_signals default

        # Track cost basis per symbol (for stop loss calculation)
        cost_basis: dict[str, float] = {}

        for trading_day_idx, d in enumerate(all_dates):
            d_str = str(d)
            is_rebalance_day = trading_day_idx % rebalance_freq == 0

            # Build price & ADV maps for this trading day
            day_prices = all_prices.filter(pl.col("trade_date") == d)
            price_map: dict[str, float] = {}
            adv_map: dict[str, float] = {}
            for row in day_prices.iter_rows(named=True):
                sym = str(row["symbol"])
                px = float(row["close"])
                vol = float(row.get("volume", 0.0) or 0.0)
                price_map[sym] = px
                if vol > 0 and px > 0:
                    adv_map[sym] = px * vol

            broker.set_prices(price_map, adv_map, d_str)

            # ═══ V2.1 Risk Exit (每日检查) ═══
            positions_df = broker.get_positions()
            # Filter zero-share stale entries (broker keeps them after full sell)
            if not positions_df.empty:
                positions_df = positions_df[positions_df["shares"] > 0]
            if not positions_df.empty:
                holdings: dict[str, int | float] = {}
                prices_for_risk: dict[str, float] = {}
                cb_for_risk: dict[str, float] = {}
                for _, pos_row in positions_df.iterrows():  # type: ignore[assignment]
                    sym = str(pos_row["symbol"])
                    shares = int(float(cast("float", pos_row["shares"])))
                    if shares > 0:
                        holdings[sym] = shares
                        prices_for_risk[sym] = price_map.get(sym, 0.0)
                        cb_for_risk[sym] = cost_basis.get(sym, 0.0)

                risk_exits = risk_mgr.evaluate_daily(
                    holdings=holdings,
                    prices=prices_for_risk,
                    cost_basis=cb_for_risk,
                    date_str=d_str,
                    stock_names=name_map,
                )

                if risk_exits:
                    for rx in risk_exits:
                        sym_shares = holdings.get(rx.symbol, 0)
                        if sym_shares > 0:
                            broker.submit_order(
                                {
                                    "symbol": rx.symbol,
                                    "side": "SELL",
                                    "quantity": sym_shares,
                                    "order_type": "market",
                                }
                            )
                            del cost_basis[rx.symbol]
                            risk_exit_hits += 1
                            if TradeReason.STOP_LOSS in rx.reasons:  # type: ignore[truthy-function]
                                stop_loss_hits += 1

            # Check for rebalance day
            day_target: list[str] = []
            day_scores_sorted: pl.DataFrame | None = None
            if is_rebalance_day and scores is not None and not scores.is_empty():
                day_scores = scores.filter(pl.col("trade_date") == d_str)
                if not day_scores.is_empty():
                    day_scores_sorted = day_scores.sort("score", descending=True)
                    day_target = day_scores_sorted["symbol"].to_list()[:top_n]

            if is_rebalance_day and day_target and day_scores_sorted is not None:
                positions_df = broker.get_positions()
                # Only count positions with actual shares (broker keeps
                # zero-share entries after a full sell — filter them out).
                live_positions = (
                    positions_df[positions_df["shares"] > 0]
                    if not positions_df.empty
                    else positions_df
                )
                n_positions_before = len(live_positions)
                target_set: set[str] = set(day_target)
                held_set: set[str] = (
                    {str(row["symbol"]) for _, row in live_positions.iterrows()}
                    if not live_positions.empty
                    else set()
                )

                # ── Sell buffer: held stocks in rank [top_n, top_n*2) stay ──
                # V2.1: Buy Top-N, Buffer 11-20 (hold), Sell >20
                buffer_n = top_n * 2
                buffer_zone: set[str] = (
                    set(day_scores_sorted["symbol"].to_list()[top_n:buffer_n])
                    if day_scores_sorted.height > top_n
                    else set()
                )

                # ── Phase 1: Sell stocks NOT in target AND NOT in buffer ──
                n_sells_submitted = 0
                keep_set = target_set | buffer_zone
                to_sell = held_set - keep_set
                if to_sell and not live_positions.empty:
                    for _, row in live_positions.iterrows():
                        sym = str(row["symbol"])
                        if sym in to_sell:
                            shares = int(float(row["shares"]))  # type: ignore[arg-type]
                            if shares > 0:
                                broker.submit_order(
                                    {
                                        "symbol": sym,
                                        "side": "SELL",
                                        "quantity": shares,
                                        "order_type": "market",
                                    }
                                )
                                n_sells_submitted += 1

                # Execute sells immediately
                sell_trades: list[Any] = []
                if n_sells_submitted > 0:
                    sell_trades = broker.execute_pending()
                    total_trades += len(sell_trades)
                    for st in sell_trades:
                        if st.side == "SELL":
                            total_sell_value += float(st.price) * st.shares

                # Clamp negative cash
                cash_now = broker.get_cash()
                if cash_now < 0:
                    logger.debug(
                        "   ⚠ 现金负数 {:.0f} → 补正为 0",
                        cash_now,
                    )
                    broker._cash = 0.0

                # ── Phase 2: Buy target stocks we don't hold ──
                after_df = broker.get_positions()
                after_df = after_df[after_df["shares"] > 0] if not after_df.empty else after_df
                after_sells = (
                    {str(row["symbol"]) for _, row in after_df.iterrows()}
                    if not after_df.empty
                    else set()
                )
                new_buys = target_set - after_sells
                buy_symbols = [s for s in day_target if s in new_buys]
                target_total = len(target_set)
                logger.debug(
                    "   🔄 {} 调仓: {}持仓→{}卖出→{}买入→目标{}只 (现金¥{:,.0f})",
                    d_str,
                    n_positions_before,
                    len(sell_trades),
                    len(buy_symbols),
                    target_total,
                    broker.get_cash(),
                )
                if buy_symbols:
                    current_equity = broker.get_equity()
                    per_stock = current_equity / max(target_total, 1)

                    for sym in buy_symbols:
                        px = price_map.get(sym, 0.0)
                        if px > 0:
                            qty = int(per_stock / px // 100 * 100)
                            if qty > 0:
                                broker.submit_order(
                                    {
                                        "symbol": sym,
                                        "side": "BUY",
                                        "quantity": qty,
                                        "order_type": "market",
                                    }
                                )

            # Execute pending orders (fills, cost deduction, position updates)
            executed = broker.execute_pending()
            total_trades += len(executed)

            # Re-mark after execution so newly bought positions have market_value
            broker.set_prices(price_map, adv_map, d_str)

            # Track cost basis for stop loss calculation
            # Clear cost basis for sold positions, set for new buys
            for ex in executed:
                sym = ex.symbol
                side = ex.side
                fill_px = float(ex.price) if ex.price else 0.0
                trade_value = fill_px * ex.shares
                if side == "SELL":
                    cost_basis.pop(sym, None)
                    total_sell_value += trade_value
                elif side == "BUY" and fill_px > 0:
                    cost_basis[sym] = fill_px
                    total_buy_value += trade_value

            eq_now = broker.get_equity()
            # Cap extreme single-day jumps (broker valuation glitch)
            if daily_equity and eq_now > daily_equity[-1] * 3:
                eq_now = daily_equity[-1]
            daily_equity.append(eq_now)

            # ── Daily benchmark: equal-weight all-stocks ──
            # Use median close (robust to penny-stock outliers)
            day_all = all_prices.filter(pl.col("trade_date") == d)
            prev_bench = daily_benchmark[-1] if daily_benchmark else initial_capital
            if not day_all.is_empty():
                day_close = day_all["close"].filter(day_all["close"] >= 1.0)
                if len(day_close) < 100:
                    day_close = day_all["close"]
                day_median = float(day_close.median())  # type: ignore[arg-type]  # polars median 类型推断噪音
                bench_now = initial_capital * (day_median / base_avg_close)
                # Cap extreme single-day jumps (>3x = data glitch)
                if bench_now > prev_bench * 3:
                    bench_now = prev_bench
                daily_benchmark.append(bench_now)
            else:
                daily_benchmark.append(prev_bench)

            if eq_now < min_equity:
                min_equity = eq_now
                min_date = d_str

        if min_equity < initial_capital * 0.2:
            n_pos = len(broker.get_positions())
            logger.warning(
                "⚠ 最低权益 ¥{:,.0f} ({:.1f}% 回撤) at {} | 持仓={}",
                min_equity,
                (1 - min_equity / initial_capital) * 100,
                min_date,
                n_pos,
            )

        final_equity = daily_equity[-1] if daily_equity else initial_capital
        total_ret = (final_equity / initial_capital - 1) * 100

        # Turnover: total sell value / average equity (cumulative, %)
        avg_equity = float(np.mean(daily_equity)) if daily_equity else initial_capital
        turnover_pct = round(total_sell_value / avg_equity * 100, 2) if avg_equity > 0 else 0.0

        # Daily returns and drawdown series (for WebUI equity curve)
        daily_return_pct: list[float] = []
        daily_drawdown: list[float] = []
        running_max_eq = initial_capital
        for i, eq in enumerate(daily_equity):
            # Daily return (%)
            if i == 0:
                daily_return_pct.append(0.0)
            else:
                prev = daily_equity[i - 1]
                daily_return_pct.append(round((eq / prev - 1) * 100, 4) if prev > 0 else 0.0)
            # Drawdown from running max (%)
            running_max_eq = max(running_max_eq, eq)
            dd = (
                round((running_max_eq - eq) / running_max_eq * 100, 2)
                if running_max_eq > 0
                else 0.0
            )
            daily_drawdown.append(dd)

        # Daily returns from equity curve
        daily_rets = [
            daily_equity[i] / daily_equity[i - 1] - 1
            for i in range(1, len(daily_equity))
            if daily_equity[i - 1] > 0
        ]
        if daily_rets:
            rets = np.array(daily_rets)
            sharpe = float(np.sqrt(252) * rets.mean() / rets.std()) if rets.std() > 0 else 0.0
            cum = np.cumprod(1 + rets)
            running_max = np.maximum.accumulate(cum)
            max_dd = (
                float(np.abs((cum - running_max).min() / running_max.max()) * 100)
                if len(cum) > 0
                else 0.0
            )
        else:
            sharpe = 0.0
            max_dd = 0.0

        return {
            "total_return_pct": round(total_ret, 2),
            "sharpe": round(sharpe, 2),
            "stop_loss_hits": stop_loss_hits,
            "risk_exit_hits": risk_exit_hits,
            "max_dd_pct": round(max_dd, 2),
            "final_equity": round(final_equity, 0),
            "n_trading_days": len(daily_equity),
            "n_trades": total_trades,
            "total_cost": round(broker.total_trading_cost, 2),
            "total_commission": round(broker.total_commission, 2),
            "total_stamp_tax": round(broker.total_stamp_tax, 2),
            "total_slippage": round(broker.total_slippage, 2),
            "turnover_pct": turnover_pct,
            # Persisted for WebUI equity curve
            "daily_equity": daily_equity,
            "daily_dates": [str(d) for d in all_dates],
            "daily_benchmark": daily_benchmark,
            "daily_drawdown": daily_drawdown,
            "daily_return_pct": daily_return_pct,
            "trade_log": broker.get_trade_log(),
        }

    @staticmethod
    def _benchmark_return(
        price_data: dict[str, pl.DataFrame],
        symbols: list[str],
        start: str,
        end: str,
    ) -> float:
        """Equal-weight buy-and-hold return for comparison.

        Caps individual stock returns at 1000% (11x) to limit the influence
        of extreme penny-stock outliers while preserving the market signal.
        Also filters stocks with initial price < 1.0 to exclude shell companies.
        """
        total_ret = 0.0
        count = 0
        # Use all loaded stocks if no symbol filter
        syms = symbols if symbols else list(price_data.keys())
        for sym in syms:
            if sym in price_data:
                df = price_data[sym]
                first = df.filter(pl.col("trade_date").cast(pl.Utf8) >= start)
                last = df.filter(pl.col("trade_date").cast(pl.Utf8) <= end)
                if not first.is_empty() and not last.is_empty():
                    px_first = float(first.head(1)["close"].item())
                    px_last = float(last.tail(1)["close"].item())
                    # Filter penny stocks (initial price < 1 yuan)
                    if px_first >= 1.0:
                        ret = px_last / px_first - 1
                        # Cap extreme returns at 1000%
                        total_ret += min(ret, 10.0)
                        count += 1
        return round(total_ret / count * 100, 2) if count > 0 else 0.0

    @staticmethod
    def _record_experiment(
        result: PipelineResult,
        start_date: str,
        end_date: str,
        dataset: str,
        experiment_id: str | None = None,
        strategy_name: str = "",
        features: list[str] | None = None,
        weights: dict[str, float] | None = None,
        top_n: int = 10,
        rebalance_freq: int = 20,
        industry_neutral: bool = False,
        orthogonalize: bool = False,
    ) -> None:
        """Persist experiment to ExperimentTracker (Rule 6: Everything is Experiment)."""
        from datetime import UTC, datetime

        from qp.research.experiment.tracker import ExperimentTracker

        if features is None:
            features = []
        if weights is None:
            weights = {}

        tracker = ExperimentTracker()
        if experiment_id is None:
            experiment_id = f"multifactor_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        # Compute annualized metrics from backtest results
        total_ret = float(result.metrics.get("total_return_pct", 0.0))
        sharpe = float(result.metrics.get("sharpe", 0.0))
        n_trading_days = int(result.metrics.get("n_trading_days", 0))
        n_years = n_trading_days / 252 if n_trading_days > 0 else 0

        # CAGR: (1 + total_ret)^(1/n_years) - 1
        annual_ret = (((1 + total_ret / 100) ** (1 / n_years)) - 1) * 100 if n_years > 0 else 0.0
        annual_vol = abs(annual_ret / sharpe) if sharpe != 0 and annual_ret != 0 else 0.0

        tracker.log_experiment(
            experiment_id=experiment_id,
            config={
                "strategy_name": strategy_name,
                "model_mode": result.metrics.get("model_mode", False),
                "description": (
                    f"Multi-factor experiment: {len(features)} factors, "
                    f"Top-{top_n}, rebalance={rebalance_freq}d"
                    f"{', industry-neutral' if industry_neutral else ''}"
                    f"{', orthogonalized' if orthogonalize else ''}"
                ),
                "dataset_version": f"{dataset}@{start_date}_{end_date}",
                "features": features,
                "model_params": dict(weights),
                "train_start": start_date,
                "train_end": end_date,
                "tags": ["multifactor", f"top{top_n}", f"rebalance{rebalance_freq}d"],
            },
            metrics={
                "ic_mean": float(result.metrics.get("ic_mean", 0.0)),
                "ic_ir": float(result.metrics.get("ic_ir", 0.0)),
                "ic_t_stat": float(result.metrics.get("ic_t_stat", 0.0)),
                "sharpe_ratio": sharpe,
                "max_drawdown_pct": float(result.metrics.get("max_dd_pct", 0.0)),
                "total_return_pct": total_ret,
                "excess_return_pct": float(result.metrics.get("excess_return_pct", 0.0)),
                "annual_return_pct": round(annual_ret, 2),
                "annual_volatility_pct": round(annual_vol, 2),
                "n_days": n_trading_days,
                "n_trades": int(result.metrics.get("n_trades", 0)),
                "turnover_pct": float(result.metrics.get("turnover_pct", 0.0)),
                "total_cost": float(result.metrics.get("total_cost", 0.0)),
                "final_equity": float(result.metrics.get("final_equity", 0.0)),
            },
            lineage_graph={
                "dataset": f"{dataset}@{start_date}",
                "model_algo": "weighted_linear",
                "strategy_id": f"multifactor_top{top_n}",
            },
        )
        logger.info("📝 实验已记录: {}", experiment_id)


# ── Q1-Q5 特征画像诊断 ───────────────────────────────────────────


def _diagnose_quintile_profiles(
    scores: pl.DataFrame,
    price_data: dict[str, pl.DataFrame],
    logger: Any,
    n_quantiles: int = 5,
) -> None:
    """Print Q1-Q5 characteristic profiles for Q5 collapse diagnosis.

    Analyzes size proxy (close×volume), volatility, and turnover per quintile
    to identify risk factor biases concentrated in extreme bins.
    """
    if scores.is_empty():
        return

    # Build flat price data with additional metrics
    parts = []
    for code, df in price_data.items():
        if df is None or df.is_empty():
            continue
        needed = ["trade_date", "close", "volume"]
        cols = [c for c in needed if c in df.columns]
        if "close" not in cols:
            continue
        has_vol = "volume" in cols
        # Compute 20d volatility and turnover per stock
        df_s = df.sort("trade_date").with_columns(
            pl.col("close").pct_change().alias("ret"),
        )
        if has_vol:
            df_s = df_s.with_columns(
                (pl.col("volume") * pl.col("close")).alias("amount"),
            )
        df_s = df_s.with_columns(
            pl.col("ret").rolling_std(20).alias("vol_20d"),
        )
        if has_vol:
            df_s = df_s.with_columns(
                (pl.col("volume") / pl.col("volume").rolling_mean(20)).alias("turnover_ratio"),
            )
        parts.append(
            df_s.select(
                [
                    pl.col("trade_date"),
                    pl.lit(str(code)).alias("symbol"),
                    pl.col("close"),
                    pl.col("ret"),
                    pl.col("vol_20d"),
                ]
                + ([pl.col("amount"), pl.col("turnover_ratio")] if has_vol else [])
            )
        )
    if not parts:
        return
    px_rich = pl.concat(parts)

    # Join with scores — align trade_date types
    score_dtype = scores.schema["trade_date"]
    if score_dtype != px_rich.schema["trade_date"]:
        px_rich = px_rich.with_columns(pl.col("trade_date").cast(score_dtype))
    merged = scores.join(px_rich, on=["trade_date", "symbol"], how="inner")
    if merged.is_empty():
        return

    # Rank ascending: Q1 = lowest scores, Q5 = highest scores (industry convention)
    merged = merged.with_columns(
        pl.col("score").rank("ordinal", descending=False).over("trade_date").alias("_rank"),
        pl.col("score").count().over("trade_date").alias("_n"),
    )
    merged = merged.with_columns(
        (pl.col("_rank") / pl.col("_n") * n_quantiles)
        .ceil()
        .clip(1, n_quantiles)
        .cast(pl.Int32)
        .alias("quintile"),
    )

    # Aggregate per quintile
    agg_exprs = [
        pl.col("score").mean().alias("avg_score"),
        pl.col("close").mean().alias("avg_price"),
        pl.col("vol_20d").mean().alias("avg_vol_20d"),
        pl.len().alias("n"),
    ]
    if "amount" in merged.columns:
        agg_exprs.append(pl.col("amount").mean().alias("avg_amount"))
    if "turnover_ratio" in merged.columns:
        agg_exprs.append(pl.col("turnover_ratio").mean().alias("avg_turnover"))

    profile = merged.group_by("quintile").agg(agg_exprs).sort("quintile")

    logger.info("")
    logger.info("   🔍 Q1-Q5 特征画像 (Q1=最低分, Q{}=最高分):", n_quantiles)
    cols_have = profile.columns
    header = "   {:5s} {:>10s} {:>10s}".format("分位", "得分均值", "波动率20d")
    if "avg_amount" in cols_have:
        header += " {:>14s}".format("日均成交额")
    if "avg_turnover" in cols_have:
        header += " {:>10s}".format("换手率比")
    header += " {:>8s}".format("样本数")
    logger.info(header)
    logger.info("   " + "-" * len(header))

    for row in profile.iter_rows(named=True):
        q = int(row["quintile"])
        line = "   Q{:<4d} {:>+10.4f} {:>10.4f}".format(
            q,
            float(row["avg_score"]),
            float(row["avg_vol_20d"] or 0.0),
        )
        if "avg_amount" in cols_have:
            amt = float(row["avg_amount"] or 0.0)
            if amt >= 1e8:
                line += f" {amt / 1e4:>12.0f}万"
            else:
                line += f" {amt:>12.0f}"
        if "avg_turnover" in cols_have:
            line += " {:>9.2f}".format(float(row["avg_turnover"] or 0.0))
        line += " {:>8d}".format(int(row["n"]))
        logger.info(line)

    # Highlight: ratio of Q5 to Q1
    n = profile.height
    if n >= n_quantiles:
        q1_row = profile.filter(pl.col("quintile") == 1)
        q5_row = profile.filter(pl.col("quintile") == n_quantiles)
        logger.info("")
        logger.info("   📊 Q5/Q1 比值 (极值端风险暴露):")
        for label, col in [
            ("波动率", "avg_vol_20d"),
            ("成交额", "avg_amount"),
            ("换手率", "avg_turnover"),
        ]:
            if col in cols_have:
                v1 = q1_row.select(pl.col(col)).item()
                v5 = q5_row.select(pl.col(col)).item()
                v1f = float(v1) if v1 is not None else 0.0
                v5f = float(v5) if v5 is not None else 0.0
                if v1f > 0:
                    ratio = v5f / v1f
                    warn = " ⚠️" if ratio > 1.5 or ratio < 0.67 else ""
                    logger.info("      {:<8s}: Q5/Q1 = {:.2f}{}", label, ratio, warn)
        logger.info("")


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _flatten_price_data(
    price_data: dict[str, pl.DataFrame],
) -> pl.DataFrame:
    """Flatten {symbol: DataFrame} into a single [trade_date, symbol, close] DataFrame."""
    parts: list[pl.DataFrame] = []
    for code, df in price_data.items():
        if df is not None and not df.is_empty():
            if "close" not in df.columns:
                continue
            parts.append(df.select(["trade_date", pl.lit(code).alias("symbol"), "close"]))
    if not parts:
        return pl.DataFrame(schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "close": pl.Float64})
    return pl.concat(parts)


def _flatten_price_data_for_backtest(
    price_data: dict[str, pl.DataFrame],
) -> pl.DataFrame:
    """Flatten {symbol: DataFrame} into [trade_date, symbol, close, volume].

    Includes volume for ADV-based liquidity checks in SimulatedBroker.
    """
    parts: list[pl.DataFrame] = []
    for code, df in price_data.items():
        if df is not None and not df.is_empty():
            if "close" not in df.columns or "trade_date" not in df.columns:
                continue
            cols = ["trade_date", "close"]
            if "volume" in df.columns:
                cols.append("volume")
            part = df.select(cols).with_columns(pl.lit(str(code)).alias("symbol"))
            parts.append(part)
    if not parts:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Utf8,
                "symbol": pl.Utf8,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        )
    return pl.concat(parts)


def _compute_factor_ic_attribution(
    price_data: dict[str, pl.DataFrame],
    valuation_data: dict[str, pl.DataFrame] | None,
    fundamental_data: dict[str, pl.DataFrame] | None,
    factor_weights: dict[str, float],
    price_flat: pl.DataFrame,
    index_df: pl.DataFrame | None = None,
    extra_factors: dict[str, dict[str, dict[str, float]]] | None = None,
) -> list[dict]:
    """Compute individual factor ICs from raw factor scores.

    Uses compute_cross_sectional_scores to get raw factor values before
    the factor pipeline (MAD/rank/neutralize/orthogonalize) is applied,
    so we can see the genuine predictive power of each factor.

    Returns list of {factor, ic_mean, ic_ir, ic_positive_pct, weight},
    sorted by |IC| descending.
    """
    from qp.research.evaluation.rank_ic import evaluate_factor_ic
    from qp.strategy.multifactor import compute_cross_sectional_scores

    if not factor_weights:
        return []

    # Compute raw factor scores (no pipeline transformations)
    # Filter to only factors that can be computed from available data:
    # - Price/volume factors from OHLCV (no index_df needed for raw IC)
    # - Fundamental factors if fundamental_data is available
    # - Valuation factors if valuation_data is available
    from qp.research.feature.compute import PRICE_VOLUME_FACTORS

    attrib_weights = dict(factor_weights)
    for fname in list(attrib_weights):
        is_available = (
            fname in PRICE_VOLUME_FACTORS
            or (valuation_data and fname in {"PE_TTM", "PB", "PCF_OCF", "Dividend_Yield", "PS_TTM"})
            or (
                fundamental_data
                and fname
                in {
                    "ROE",
                    "revenue_growth",
                    "net_profit_growth",
                    "gross_margin",
                    "net_margin",
                    "debt_ratio",
                    "EPS",
                    "NAV",
                    "ROE_Level",
                    "Profit_Stability",
                    "Earnings_Quality",
                    "Margin_Composite",
                    "cashflow_per_share",
                }
            )
            or (extra_factors and fname in extra_factors)
        )
        # Residual_Momentum_3M requires index_df to compute
        if fname == "Residual_Momentum_3M" and index_df is None:
            is_available = False
        if not is_available:
            attrib_weights.pop(fname)
    if not attrib_weights:
        return []

    try:
        scores_result = compute_cross_sectional_scores(
            price_data=price_data,
            weights=attrib_weights,
            valuation_data=valuation_data,
            fundamental_data=fundamental_data,
            industry_neutral=False,  # raw — no transformations
            orthogonalize=False,
            return_diagnostics=True,
            extra_factors=extra_factors,  # reuse from strategy run
            index_df=index_df,
        )
    except Exception as e:
        logger.warning("   因子归因跳过: 无法计算原始因子得分 ({})", e)
        return []

    if not isinstance(scores_result, tuple):
        return []

    _scores, diagnostics = scores_result
    all_factors = diagnostics.get("all_factors", {})

    if not all_factors:
        return []

    # Flatten each factor from {date: {code: {factor: value}}} to DataFrame
    results = []
    for fname in sorted(factor_weights.keys()):
        rows = []
        for date_str, stocks in all_factors.items():
            for code, factors in stocks.items():
                if fname in factors:
                    val = factors[fname]
                    if val is not None and val == val:  # not NaN
                        rows.append(
                            {
                                "trade_date": date_str,
                                "symbol": code,
                                "score": float(val),
                            }
                        )
        if len(rows) < 100:
            continue

        factor_df = pl.DataFrame(
            rows, schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "score": pl.Float64}
        )
        ic = evaluate_factor_ic(factor_df, price_flat, forward_days=5, min_stocks_per_day=10)

        if ic.n_days >= 10:
            results.append(
                {
                    "factor": fname,
                    "ic_mean": ic.ic_mean,
                    "ic_ir": ic.ic_ir,
                    "ic_positive_pct": ic.ic_positive_pct,
                    "weight": factor_weights.get(fname, 0.0),
                    "n_days": ic.n_days,
                }
            )

    # ── Persist factor health data (DP-002: auto-collect during experiment) ──
    _persist_factor_health(results, all_factors, price_flat)

    # Sort by absolute IC descending
    results.sort(key=lambda x: abs(x["ic_mean"]), reverse=True)
    return results


def _persist_factor_health(
    results: list[dict],
    all_factors: dict[str, dict[str, dict[str, float]]],
    price_flat: pl.DataFrame,
) -> None:
    """Persist per-factor health data to factor_health.parquet (DP-002 v4).

    Called after factor IC attribution during every experiment run.
    Computes daily IC series per factor, classifies health stage,
    saves daily IC series for correlation analysis, computes
    multi-horizon decay curves, and logs to FactorHealthLogger.

    Args:
        results: List of {factor, ic_mean, ic_ir, ...} dicts.
        all_factors: {date: {code: {factor_name: value}}} nested dict.
        price_flat: Flat price DataFrame for forward return calculation.
    """
    if not results or not all_factors:
        return

    try:
        import contextlib
        from datetime import UTC, datetime

        from qp.monitoring.factor_health import FactorHealthMonitor
        from qp.monitoring.factor_health_logger import FactorHealthLogger
        from qp.research.evaluation.rank_ic import (
            compute_daily_ic_series,
            compute_ic_decay,
            evaluate_factor_ic,
        )

        monitor = FactorHealthMonitor()
        health_logger = FactorHealthLogger()
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        logged = 0

        for entry in results:
            fname = entry["factor"]

            # ── Guard: don't overwrite full-history data with experiment subset ──
            existing = health_logger.load_latest(fname)
            if existing and existing.get("n_days", 0) > entry.get("n_days", 0) * 1.5:
                # Existing data covers substantially more days — skip experiment write
                continue

            # Build per-factor score DataFrame from all_factors
            rows = []
            for date_str, stocks in all_factors.items():
                for code, factors in stocks.items():
                    if fname in factors:
                        val = factors[fname]
                        if val is not None and val == val:  # not NaN
                            rows.append(
                                {
                                    "trade_date": date_str,
                                    "symbol": code,
                                    "score": float(val),
                                }
                            )
            if len(rows) < 100:
                continue

            fdf = pl.DataFrame(
                rows,
                schema={"trade_date": pl.Utf8, "symbol": pl.Utf8, "score": pl.Float64},
            )
            ic_full = evaluate_factor_ic(fdf, price_flat, forward_days=5, min_stocks_per_day=10)
            if ic_full.n_days < 10:
                continue

            # ── Daily IC series persistence (for correlation analysis) ──
            with contextlib.suppress(Exception):
                daily_records = compute_daily_ic_series(
                    fdf, price_flat, forward_days=5, min_stocks_per_day=10
                )
                health_logger.save_daily_ic_series(fname, daily_records)

            # ── Multi-horizon IC decay (1d/3d/5d/10d/20d) ──
            multi_horizon: dict[int, float] = {}
            with contextlib.suppress(Exception):
                decay_results = compute_ic_decay(fdf, price_flat, min_stocks_per_day=10)
                for h, rec in decay_results.items():
                    multi_horizon[h] = rec.ic_mean

            status = monitor.check_factor(fname, ic_full.daily_ics)
            health_logger.log(status, date_str=today_str, multi_horizon_ic=multi_horizon)
            logged += 1

        # ── Factor Store integration: save raw factor data (DP-002 §4.3) ──
        if logged:
            with contextlib.suppress(Exception):
                from qp.data.factor_store.store import FactorStore

                # Convert all_factors {date: {symbol: {factor: value}}} to DataFrame
                store_rows: list[dict[str, Any]] = []
                for d, stocks in all_factors.items():
                    for sym, factors in stocks.items():
                        row: dict[str, Any] = {"trade_date": d, "symbol": sym}
                        row.update(factors)
                        store_rows.append(row)
                if store_rows:
                    store_df = pl.DataFrame(store_rows)
                    store = FactorStore()
                    store.save_raw(f"experiment_{today_str}", store_df)
                    logger.info("   ✅ 因子数据已写入 FactorStore (raw tier)")

        if logged:
            logger.info("   ✅ 因子健康已写入: {} 个因子 → factor_health.parquet", logged)
    except Exception as e:
        logger.warning("   因子健康记录失败 (非致命): {}", e)


def _log_factor_ic_table(
    factor_ic_table: list[dict],
    factor_weights: dict[str, float],
) -> None:
    """Log a formatted factor IC attribution table."""
    if not factor_ic_table:
        return

    # Header
    logger.info(
        "   {:28s} {:>10s} {:>8s} {:>8s} {:>8s}".format(
            "因子 / Factor", "IC Mean", "IC IR", "IC>0%", "权重/Wt"
        )
    )
    logger.info("   " + "-" * 70)

    # Rows
    total_ic = sum(abs(e["ic_mean"]) for e in factor_ic_table) or 1.0
    for entry in factor_ic_table:
        fname = entry["factor"]
        ic_val = entry["ic_mean"]
        ic_ir = entry["ic_ir"]
        ic_pct = entry["ic_positive_pct"]
        wt = entry["weight"]
        contrib_pct = abs(ic_val) / total_ic * 100

        # Direction markers
        direction = "✅" if ic_val > 0 else "🔴"

        logger.info(
            f"   {direction} {fname:25s} {ic_val:>+9.4f} {ic_ir:>7.2f} {ic_pct:>7.0f}% {wt:>+7.3f} ({contrib_pct:.0f}%)"
        )

    # ── Factor direction-aware mismatch check ──
    # sign(weight) must match sign(IC_raw).  The builtin direction cancels:
    #   effective_contribution = norm * direction * weight
    #   effective_IC = direction * IC_raw
    #   Aligning them → sign(weight) = sign(IC_raw)
    positive = [e for e in factor_ic_table if e["ic_mean"] > 0]
    negative = [e for e in factor_ic_table if e["ic_mean"] < 0]
    weight_mismatch = []
    for e in factor_ic_table:
        fname = e["factor"]
        wt = e["weight"]
        ic = e["ic_mean"]
        if ic == 0 or wt == 0:
            continue
        # sign(weight) must match sign(IC_raw).
        # builtin_dir cancels out: effective_contribution = direction * weight,
        # effective_IC = direction * IC_raw.  Aligning them → sign(wt) == sign(IC_raw).
        if (ic > 0 and wt < 0) or (ic < 0 and wt > 0):
            weight_mismatch.append(e)

    logger.info("   " + "-" * 70)
    logger.info(
        "   正向贡献: {} 因子 | 负向贡献: {} 因子 | 权重方向错误: {} 因子",
        len(positive),
        len(negative),
        len(weight_mismatch),
    )

    if weight_mismatch:
        names = [e["factor"] for e in weight_mismatch]
        logger.warning("   ⚠ 有效权重方向与 IC 符号相反: {}", ", ".join(names))
        logger.warning("      建议翻转权重符号或降低这些因子的权重")


def _optimize_weights_from_ic(
    factor_ic_table: list[dict],
    current_weights: dict[str, float],
    min_ic_threshold: float = 0.02,
) -> dict[str, float]:
    """Optimize factor weights from IC attribution on the full dataset.

    Algorithm:
      1. Drop factors with |IC| < min_ic_threshold (noise, breaks monotonicity)
      2. sign(weight) = sign(IC_raw)
         — builtin_dir is already handled by the combine_factors pipeline,
         so the weight sign only needs to match the raw factor IC direction.
      3. Weight magnitude ∝ |IC|
      4. Normalize so sum of absolute weights = 1.0

    This replaces the old 18-stock-tuned weights with data-driven weights
    computed on the full 3039-stock universe.
    """
    ic_map = {e["factor"]: e["ic_mean"] for e in factor_ic_table}
    optimized: dict[str, float] = {}
    dropped: list[str] = []

    for fname in current_weights:
        ic = ic_map.get(fname, 0.0)
        if abs(ic) >= min_ic_threshold:
            # sign(weight) = sign(IC_raw).
            # builtin_dir cancels out (see _log_factor_ic_table for derivation),
            # so the weight simply follows the raw IC direction.
            optimized[fname] = ic
        else:
            dropped.append(fname)

    if dropped:
        logger.info(
            "   🗑 移除弱因子 (|IC|<{:.0%}): {} — {} 因子",
            min_ic_threshold,
            ", ".join(dropped),
            len(dropped),
        )

    # Normalize so sum(|w|) = 1.0
    total_abs = sum(abs(w) for w in optimized.values())
    if total_abs > 0:
        optimized = {k: v / total_abs for k, v in optimized.items()}

    return optimized


def _log_weight_optimization(
    old_weights: dict[str, float],
    new_weights: dict[str, float],
) -> None:
    """Log the weight optimization results."""
    logger.info("   {:28s} {:>10s} {:>10s} {:>10s}".format("因子", "旧权重", "新权重", "变化"))
    logger.info("   " + "-" * 68)
    for fname in sorted(old_weights.keys()):
        old_w = old_weights[fname]
        new_w = new_weights.get(fname, old_w)
        change = "翻转" if old_w * new_w < 0 else ("↑" if abs(new_w) > abs(old_w) else "↓")
        logger.info(f"   {fname:25s} {old_w:>+9.3f} {new_w:>+9.3f}  {change:>4s}")


def _build_optimized_config(
    strategy_name: str,
    optimized_weights: dict[str, float],
) -> StrategyConfig | None:
    """Build a StrategyConfig with optimized weights."""
    from dataclasses import replace

    from qp.strategy.config import get_strategy_config

    try:
        base = get_strategy_config(strategy_name)
        return replace(base, factors=dict(optimized_weights))
    except Exception:
        return None


# ── Score Band Auto-Search ───────────────────────────────────────

AUTO_SCORE_BANDS: list[tuple[str, float, float]] = [
    ("Top5 (Q5)", 80, 100),
    ("Q4", 60, 80),
    ("Q3-Q4", 40, 80),
    ("Q2-Q4", 20, 80),
    ("Full (0-100)", 0, 100),
]


def _auto_search_score_band(
    scores: pl.DataFrame,
    price_flat: pl.DataFrame,
    config: Any,
) -> list[dict]:
    """Enumerate score bands and compare layered return metrics.

    Uses compute_layered_returns for fast signal-quality evaluation
    without full broker simulation.

    Returns list of {band, top_bottom_spread, monotonicity_t_stat, n_days}, sorted by t_stat.
    """
    from qp.research.evaluation.layered_test import compute_layered_returns

    results = []
    for label, pct_min, pct_max in AUTO_SCORE_BANDS:
        try:
            # Filter scores to band
            if pct_min > 0 or pct_max < 100:
                band_scores = scores.with_columns(
                    pl.col("score").rank("ordinal", descending=True).alias("_rank"),
                )
                n_total = band_scores.height
                rank_lo = int(n_total * pct_min / 100)
                rank_hi = int(n_total * pct_max / 100)
                band_scores = band_scores.filter(
                    (pl.col("_rank") > rank_lo) & (pl.col("_rank") <= rank_hi)
                ).drop("_rank")
            else:
                band_scores = scores

            if band_scores.is_empty():
                results.append({"band": label, "error": "empty"})
                continue

            # Layered return analysis (fast, no broker)
            layered = compute_layered_returns(band_scores, price_flat, n_quantiles=5)
            results.append(
                {
                    "band": label,
                    "pct_min": pct_min,
                    "pct_max": pct_max,
                    "top_bottom_spread": layered.top_bottom_spread,
                    "monotonicity_t_stat": layered.monotonicity_t_stat,
                    "n_days": layered.n_days,
                }
            )
        except Exception as e:
            results.append({"band": label, "error": str(e)[:40]})

    # Log comparison table
    logger.info("")
    logger.info("   🔍 Score Band 自动搜索:")
    logger.info("   {:16s} {:>8s} {:>10s} {:>10s}".format("Band", "Spread", "t_mono", "N Days"))
    logger.info("   " + "-" * 48)
    for r in results:
        if "error" in r:
            logger.info("   {:16s} ❌ {}", r["band"], r["error"])
            continue
        t_mono = r["monotonicity_t_stat"]
        marker = "✅" if t_mono >= 2.0 else ("⚠" if t_mono >= 1.0 else "❌")
        logger.info(
            "   {:16s} {} {:+.4f} {:>9.2f} {:>9d}",
            r["band"],
            marker,
            r["top_bottom_spread"],
            t_mono,
            r["n_days"],
        )

    return sorted(
        [r for r in results if "error" not in r],
        key=lambda r: r["monotonicity_t_stat"],
        reverse=True,
    )


def _archive_research_debt(
    strategy_name: str,
    ic_record: ICRecord,
    layered: LayeredTestResult,
    failures: list[str],
    start: str,
    end: str,
    gate_result: object | None = None,
) -> str:
    """Archive failed factor research per Rule 12 (Pay Down Research Debt).

    Uses KnowledgeArchive for structured, queryable YAML frontmatter entries.

    rule.md §10.1: 不满足条件的因子只能进入 Research Debt Archive,
    避免在相同错误方向上重复浪费时间。

    Returns:
        entry_id of the archived research debt entry.
    """

    from qp.knowledge.archive import KnowledgeArchive

    # ── Build parameterized next steps based on failure type ──
    next_steps: list[str] = []
    has_ic_fail = any("IC" in f for f in failures)
    has_mono_fail = any("单调" in f for f in failures) or any("mono" in f.lower() for f in failures)
    has_spread_fail = any("spread" in f.lower() for f in failures) or any(
        "Q5" in f for f in failures
    )

    if has_ic_fail:
        next_steps.append("- [ ] 检查因子计算是否有错误（前视偏差、数据对齐）")
        next_steps.append("- [ ] 考虑替换弱因子 (|IC| < 0.02) 或调整因子定义")
    if has_mono_fail:
        next_steps.append("- [ ] 研究 Q5 顶部塌陷原因（价值陷阱 / 极端反转）")
        next_steps.append("- [ ] 尝试非线性得分变换或叠加质量过滤")
    if has_spread_fail:
        next_steps.append("- [ ] 扩大持仓数量 (Top10 → Top30) 或缩短调仓周期")
        next_steps.append("- [ ] 测试不同 forward period 下的 spread 稳定性")
    if not next_steps:
        next_steps = [
            "- [ ] 回到因子计算，检查原始因子值是否有计算错误",
            "- [ ] 缩减因子数量，只保留 |IC| > 0.03 的因子",
            "- [ ] 检查数据源是否有前视偏差",
        ]

    # ── Build content ──
    failure_lines = "\n".join(f"- ❌ {f}" for f in failures)
    content = f"""## Context
**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Period**: {start} → {end}
**Strategy**: {strategy_name}

## Failed Thresholds (§10.1)

{failure_lines}

## Metrics

| Metric | Value | Threshold |
|--------|-------|-----------|
| IC Mean | {ic_record.ic_mean:+.4f} | \\|IC\\| ≥ 0.02 |
| IC IR | {ic_record.ic_ir:.2f} | ≥ 0.3 |
| IC t-stat | {ic_record.ic_t_stat:.2f} | ≥ 2.0 |
| IC>0% | {ic_record.ic_positive_pct:.1f}% | — |
| Q5-Q1 spread | {layered.top_bottom_spread:+.4f} | t ≥ 2.0 |
| Spread t | {layered.spread_t_stat:.2f} | ≥ 2.0 |
| Monotonicity t | {layered.monotonicity_t_stat:.2f} | ≥ 2.0 |
| N days | {ic_record.n_days} | — |

## Next Steps

{chr(10).join(next_steps)}

---
*Archived by MultiFactorPipeline §10.1 Gate*
"""

    # ── Determine primary failure for tagging ──
    if has_mono_fail:
        primary = "portfolio_conversion_failure"
    elif has_ic_fail:
        primary = "factor_validity_failure"
    else:
        primary = "gate_failure"

    archive = KnowledgeArchive()
    entry = archive.create_research_debt(
        title=f"{strategy_name} — Gate Failure: {primary.replace('_', ' ').title()}",
        content=content,
        tags=[strategy_name, "gate_failure", primary],
        metadata={
            "strategy_id": str(strategy_name),
            "gate_stage": "backtest_passed",
            "ic_mean": f"{ic_record.ic_mean:+.4f}",
            "ic_ir": f"{ic_record.ic_ir:.2f}",
            "q5_q1_spread": f"{layered.top_bottom_spread:+.4f}",
            "monotonicity_t": f"{layered.monotonicity_t_stat:.2f}",
            "n_days": str(ic_record.n_days),
        },
    )

    logger.info("   📋 已归档到 Research Debt: {}", entry.entry_id)
    return entry.entry_id


def _build_industry_map(
    price_data: dict[str, pl.DataFrame],
) -> dict[str, str] | None:
    """Build {symbol: industry} from price data if industry column exists."""
    for df in price_data.values():
        if df is not None and "industry" in df.columns:
            mapping: dict[str, str] = {}
            for code, stock_df in price_data.items():
                if stock_df is not None and "industry" in stock_df.columns:
                    ind = str(stock_df["industry"].tail(1).item() or "")
                    if ind:
                        mapping[code] = ind
            if mapping:
                return mapping
            break
    return None
