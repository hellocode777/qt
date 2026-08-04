"""CLI command handlers for the "experiment" group."""

from __future__ import annotations

import sys


def cmd_experiment_compare() -> int:
    """Compare recent experiments side-by-side."""
    from qp.research.experiment import ExperimentTracker

    tracker = ExperimentTracker()
    records = tracker.list_experiments()

    if not records:
        print("无实验记录")
        return 0

    # Build comparison rows from tracker records
    import math

    experiments = []
    for r in records:
        cfg = r.config
        m = r.metrics
        experiments.append(
            {
                "id": cfg.experiment_id,
                "strategy": cfg.strategy_name or "?",
                "n_factors": len(cfg.features),
                "model": "ML" if cfg.model_mode else "线性",
                "ic_mean": m.ic_mean,
                "ic_ir": m.ic_ir,
                "sharpe": m.sharpe_ratio,
                "total_return": m.total_return_pct,
                "max_dd": m.max_drawdown_pct,
                "excess_return": m.excess_return_pct,
                "status": r.status.value,
            }
        )

    if not experiments:
        print("无实验记录")
        return 0

    def _fmt(val: float, suffix: str = "", width: int = 7) -> str:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return "N/A".rjust(width)
        return f"{val:+{width}.2f}{suffix}"

    header = (
        f"{'实验ID':<30s} {'策略':>16s} {'因子':>4s} {'模型':>4s} "
        f"{'IC':>7s} {'IC_IR':>6s} {'收益':>8s} {'夏普':>6s} {'回撤':>7s} {'超额':>8s}"
    )
    print(header)
    print("-" * len(header))
    for e in experiments[:20]:  # last 20
        print(
            f"{e['id']:<30s} {e['strategy']:>16s} {e['n_factors']:>4d} {e['model']:>4s} "
            f"{_fmt(e['ic_mean'])} {_fmt(e['ic_ir'], width=6)} {_fmt(e['total_return'], '%', 8)} "
            f"{_fmt(e['sharpe'], width=6)} {_fmt(e['max_dd'], '%', 7)} {_fmt(e['excess_return'], '%', 8)}"
        )

    print()
    print(f"共 {len(experiments)} 个实验, 显示最近 20 个")
    return 0


def cmd_experiment_list() -> int:
    """List tracked experiments with optional filtering."""
    from qp.research.experiment import ExperimentTracker

    tracker = ExperimentTracker()
    records = tracker.list_experiments()

    if not records:
        print("(empty)")
        print("  暂无实验记录。运行 qp run daily 后将自动记录实验。")
        return 0

    # Parse filter options from sys.argv[3:]
    strategy_filter = ""
    min_sharpe = float("-inf")
    min_ic = float("-inf")
    min_return = float("-inf")
    show_n = 0

    args = sys.argv[3:] if len(sys.argv) > 3 else []
    for a in args:
        if a.startswith("--strategy="):
            strategy_filter = a.split("=", 1)[1]
        elif a.startswith("--min-sharpe="):
            min_sharpe = float(a.split("=", 1)[1])
        elif a.startswith("--min-ic="):
            min_ic = float(a.split("=", 1)[1])
        elif a.startswith("--min-return="):
            min_return = float(a.split("=", 1)[1])
        elif a.startswith("-n="):
            show_n = int(a.split("=", 1)[1])

    # Apply filters
    if strategy_filter:
        records = [
            r
            for r in records
            if r.config.strategy_name and strategy_filter in r.config.strategy_name
        ]
    if min_sharpe != float("-inf"):
        records = [r for r in records if r.metrics.sharpe_ratio >= min_sharpe]
    if min_ic != float("-inf"):
        records = [r for r in records if r.metrics.ic_mean >= min_ic]
    if min_return != float("-inf"):
        records = [r for r in records if r.metrics.total_return_pct >= min_return]
    if show_n > 0:
        records = records[:show_n]

    if not records:
        print("(empty — no experiments match filters)")
        return 0

    # Print active filters
    filters = []
    if strategy_filter:
        filters.append(f"strategy~~{strategy_filter}")
    if min_sharpe != float("-inf"):
        filters.append(f"sharpe≥{min_sharpe:.1f}")
    if min_ic != float("-inf"):
        filters.append(f"IC≥{min_ic:.3f}")
    if min_return != float("-inf"):
        filters.append(f"return≥{min_return:.1f}%")
    if filters:
        print(f"过滤条件: {', '.join(filters)}")
        print()

    print(f"{'ID':<32s} {'策略':>16s} {'Sharpe':>7s} {'IC':>8s} {'Ret':>8s} {'回撤':>7s}  Lineage")
    print("-" * 110)
    for r in records:
        strategy = r.config.strategy_name or "?"
        if len(strategy) > 16:
            strategy = strategy[:13] + "..."
        print(
            f"{r.config.experiment_id:<32s} "
            f"{strategy:>16s} "
            f"{r.metrics.sharpe_ratio:>6.2f} "
            f"{r.metrics.ic_mean:>7.4f} "
            f"{r.metrics.total_return_pct:>7.1f}% "
            f"{r.metrics.max_drawdown_pct:>6.1f}% "
            f" {r.lineage.chain_str()}"
        )
    print(f"\n共 {len(records)} 条记录")
    return 0


def cmd_experiment_show(experiment_id: str | None = None) -> int:
    """Show experiment details."""
    if not experiment_id:
        print("用法: qp experiment show <experiment_id>")
        return 1

    from qp.research.experiment import ExperimentTracker

    tracker = ExperimentTracker()
    record = tracker.get(experiment_id)

    if record is None:
        print(f"实验 {experiment_id} 未找到 / Experiment not found")
        return 1

    print(f"=== 实验详情 / Experiment: {experiment_id} ===")
    print()
    print(f"  状态 / Status:       {record.status.value}")
    print(f"  创建时间 / Created:   {record.config.created_at.isoformat()}")
    print(f"  描述 / Description:  {record.config.description or '(none)'}")
    print()
    print("  ── 配置 / Config ──")
    print(f"    特征 / Features:    {record.config.features}")
    print(f"    数据版本 / Dataset:  {record.config.dataset_version}")
    print(f"    CV折数 / CV Folds:   {record.config.cv_folds}")
    if record.config.model_params:
        print(f"    模型参数 / Model:    {record.config.model_params}")
    print()
    print("  ── 指标 / Metrics ──")
    print(f"    IC均值 / IC Mean:      {record.metrics.ic_mean:.4f}")
    print(f"    IC_IR:                 {record.metrics.ic_ir:.2f}")
    print(f"    IC t-stat:             {record.metrics.ic_t_stat:.2f}")
    print(f"    夏普比率 / Sharpe:      {record.metrics.sharpe_ratio:.2f}")
    print(f"    最大回撤 / MaxDD:       {record.metrics.max_drawdown_pct:.1f}%")
    print(f"    总收益 / Total Return:  {record.metrics.total_return_pct:.1f}%")
    print(f"    样本内IC / In-Sample:   {record.metrics.in_sample_ic:.4f}")
    print(f"    样本外IC / Out-of-Sample: {record.metrics.out_of_sample_ic:.4f}")
    print()
    print("  ── 血缘 / Lineage ──")
    print(f"    {record.lineage.chain_str()}")
    if record.errors:
        print()
        print("  ── 错误 / Errors ──")
        for e in record.errors:
            print(f"    {e}")

    return 0


def cmd_experiment_run() -> int:
    """Run a named experiment pipeline (e.g. multifactor)."""
    if len(sys.argv) < 4:
        print("qp experiment run <name> [options]", file=sys.stderr)
        print("  Available: multifactor", file=sys.stderr)
        print("  Options:", file=sys.stderr)
        print(
            "    --strategy momentum_vol_full  Strategy name. Use ',' for batch: v1,v2",
            file=sys.stderr,
        )
        print("    --compare                    Force comparison mode", file=sys.stderr)
        print("    --symbols 000001,000002,...   Stock codes", file=sys.stderr)
        print("    --start 2024-01-01           Start date", file=sys.stderr)
        print("    --end 2026-07-20             End date", file=sys.stderr)
        print("    --top-n 10                   Top N stocks", file=sys.stderr)
        print("    --quality-filter=true/false  Enable/disable quality filter", file=sys.stderr)
        print("    --quality-min-roe=0.05       Minimum ROE for quality filter", file=sys.stderr)
        print("    --rebalance 20               Rebalance frequency (days)", file=sys.stderr)
        print("    --industry-neutral           Enable industry neutralization", file=sys.stderr)
        print("    --orthogonalize              Enable factor orthogonalization", file=sys.stderr)
        print(
            "    --score-band 60-80          Score percentile band (Q4 sweet spot)",
            "    --score-band auto            Auto-search all bands and compare",
            file=sys.stderr,
        )
        print("    --debug                     Enable DEBUG-level logging", file=sys.stderr)
        print("    --resume <experiment_id>    Reproduce experiment from snapshot", file=sys.stderr)
        return 1

    pipeline_name = sys.argv[3]

    if pipeline_name != "multifactor":
        print(
            f"qp experiment run: unknown pipeline '{pipeline_name}'. Try: multifactor",
            file=sys.stderr,
        )
        return 1

    # Parse options
    from loguru import logger as _loguru_logger

    # Default to INFO unless --debug is passed (loguru defaults to DEBUG)
    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name: <32}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    from qp.pipeline.multifactor_pipeline import MultiFactorPipeline
    from qp.platform.pipeline.context import PipelineContext

    params: dict[str, object] = {}
    args = sys.argv[4:]
    debug_mode = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--debug":
            debug_mode = True
            i += 1
            continue
        if arg.startswith("--symbols="):
            params["symbols"] = arg.split("=", 1)[1].split(",")
        elif arg == "--symbols" and i + 1 < len(args):
            i += 1
            params["symbols"] = args[i].split(",")
        elif arg.startswith("--start="):
            params["start_date"] = arg.split("=", 1)[1]
        elif arg == "--start" and i + 1 < len(args):
            i += 1
            params["start_date"] = args[i]
        elif arg.startswith("--end="):
            params["end_date"] = arg.split("=", 1)[1]
        elif arg == "--end" and i + 1 < len(args):
            i += 1
            params["end_date"] = args[i]
        elif arg.startswith("--top-n="):
            params["top_n"] = int(arg.split("=", 1)[1])
        elif arg.startswith("--rebalance="):
            params["rebalance_freq"] = int(arg.split("=", 1)[1])
        elif arg == "--industry-neutral":
            params["industry_neutral"] = True
        elif arg == "--orthogonalize":
            params["orthogonalize"] = True
        elif arg == "--skip-gate":
            params["skip_gate"] = True
        elif arg.startswith("--resume="):
            params["resume"] = arg.split("=", 1)[1]
        elif arg == "--resume" and i + 1 < len(args):
            i += 1
            params["resume"] = args[i]
        elif arg == "--model":
            params["model_mode"] = True
        elif arg == "--compare":
            params["compare"] = True
        elif arg.startswith("--strategy="):
            params["strategy"] = arg.split("=", 1)[1]
        elif arg == "--strategy" and i + 1 < len(args):
            i += 1
            params["strategy"] = args[i]
        elif arg.startswith("--quality-filter="):
            params["quality_filter"] = arg.split("=", 1)[1].lower() in ("true", "1", "yes")
        elif arg == "--quality-filter" and i + 1 < len(args):
            i += 1
            params["quality_filter"] = args[i].lower() in ("true", "1", "yes")
        elif arg.startswith("--quality-min-roe="):
            params["quality_min_roe"] = float(arg.split("=", 1)[1])
        elif arg == "--quality-min-roe" and i + 1 < len(args):
            i += 1
            params["quality_min_roe"] = float(args[i])
        elif arg.startswith("--score-band="):
            params["score_band"] = arg.split("=", 1)[1]
        elif arg == "--score-band" and i + 1 < len(args):
            i += 1
            params["score_band"] = args[i]
        i += 1

    # Check if comma-separated strategy list for batch run
    if debug_mode:
        _loguru_logger.remove()
        _loguru_logger.add(
            sys.stderr,
            level="DEBUG",
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name: <32}</cyan> | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )
        _loguru_logger.debug("🐛 Debug mode enabled")

    # ── Resume/Reproduce mode ──
    resume_id = str(params.get("resume", ""))
    if resume_id:
        import json as _json
        from pathlib import Path as _Path

        exp_json = _Path("data/experiments") / f"{resume_id}.json"
        if not exp_json.exists():
            print(f"实验记录不存在: {exp_json}", file=sys.stderr)
            return 1

        with open(exp_json, encoding="utf-8") as _fh:
            exp_data = _json.load(_fh)

        exp_cfg: dict[str, object] = exp_data.get("config", {})  # type: ignore[assignment]
        snapshot_file = _Path("data/experiments") / resume_id / "price_data.parquet"
        if not snapshot_file.exists():
            print(f"实验快照不存在: {snapshot_file}", file=sys.stderr)
            print("该实验可能是在快照功能上线前运行的，无法复现。", file=sys.stderr)
            return 1

        # Auto-fill params from experiment record (CLI args override)
        for key, param_key in [
            ("strategy_name", "strategy"),
            ("train_start", "start_date"),
            ("train_end", "end_date"),
            ("top_n", "top_n"),
            ("rebalance_freq", "rebalance_freq"),
        ]:
            if param_key not in params and exp_cfg.get(key):
                params[param_key] = exp_cfg[key]

        # Extract frozen weights from model_params (weighted_linear) or factors
        frozen_wt: dict[str, float] = {}
        model_params_raw = exp_cfg.get("model_params", {})
        if isinstance(model_params_raw, dict):
            for k, v in model_params_raw.items():
                frozen_wt[str(k)] = float(v)  # type: ignore[arg-type]
        if not frozen_wt and isinstance(
            exp_data.get("metrics", {}).get("feature_importance"), dict
        ):
            for k, v in exp_data["metrics"]["feature_importance"].items():
                frozen_wt[str(k)] = float(v)

        params["data_snapshot"] = str(snapshot_file)
        params["freeze_weights"] = frozen_wt
        # Use the original experiment's dataset label for the lineage record
        params["dataset"] = str(exp_cfg.get("dataset_version", "daily_price_latest"))

        print(f"📸 复现实验: {resume_id}")
        print(f"   策略: {params.get('strategy')}")
        print(f"   区间: {params.get('start_date')} → {params.get('end_date')}")
        print(f"   权重: {frozen_wt}")
        print(f"   快照: {snapshot_file}")
        print()

    strategy_val = str(params.get("strategy", ""))
    strategies: list[str] = []
    if "," in strategy_val:
        strategies = [s.strip() for s in strategy_val.split(",") if s.strip()]
        params["compare"] = True
    else:
        strategies = [strategy_val] if strategy_val else [""]

    if len(strategies) > 1:
        # Batch run mode
        all_results: list[dict[str, object]] = []
        for strat in strategies:
            strat_params = dict(params)
            strat_params["strategy"] = strat
            print(f"\n{'=' * 60}")
            print(f"  运行策略: {strat}")
            print(f"{'=' * 60}")
            ctx = PipelineContext(pipeline_name="multifactor_experiment", parameters=strat_params)
            pipeline = MultiFactorPipeline()
            result = pipeline.run(ctx)
            all_results.append(
                {
                    "strategy": strat,
                    "status": result.status.value,
                    "metrics": dict(result.metrics),
                }
            )
            if result.status.value != "success":
                print(f"  ⚠ {strat} 失败: {result.errors}")

        # Print comparison table
        print(f"\n{'=' * 60}")
        print("  批量实验对比 / Batch Comparison")
        print(f"{'=' * 60}")
        print(
            f"{'策略':>24s} {'状态':>8s} {'IC':>7s} {'IC_IR':>6s} {'Sharpe':>7s} {'收益':>8s} {'回撤':>7s}"
        )
        print("-" * 75)
        for r in all_results:
            m: dict[str, float] = r["metrics"]  # type: ignore[misc]
            print(
                f"{str(r['strategy']):>24s} {str(r['status']):>8s} "
                f"{float(m.get('ic_mean', 0)):+7.4f} "
                f"{float(m.get('ic_ir', 0)):+6.2f} "
                f"{float(m.get('sharpe_ratio', 0)):+6.2f} "
                f"{float(m.get('total_return_pct', 0)):+7.1f}% "
                f"{float(m.get('max_drawdown_pct', 0)):+6.1f}%"
            )
        return 0

    # Single strategy run
    context = PipelineContext(pipeline_name="multifactor_experiment", parameters=params)
    pipeline = MultiFactorPipeline()
    result = pipeline.run(context)

    if result.status.value != "success":
        return 1

    # Print summary
    logger = __import__("loguru").logger
    logger.info("")
    logger.info("── 实验指标 / Metrics ──")
    for k, v in sorted(result.metrics.items()):
        if isinstance(v, float):
            if abs(v) < 0.01:
                logger.info("  {}: {:.4f}", k, v)
            elif abs(v) < 1:
                logger.info("  {}: {:.2f}", k, v)
            else:
                logger.info("  {}: {:.1f}", k, v)

    return 0


def cmd_experiment_validate(experiment_id: str | None = None) -> int:
    """Validate an experiment against Layer 5 Gate criteria."""
    if not experiment_id:
        print("qp experiment validate <experiment_id>", file=sys.stderr)
        print("  Loads a completed experiment and runs the full Layer 5", file=sys.stderr)
        print("  Validation Gate, printing a structured report.", file=sys.stderr)
        return 1

    from qp.research.experiment.tracker import ExperimentTracker

    tracker = ExperimentTracker()
    record = tracker.get(experiment_id)
    if record is None:
        print(f"❌ 实验不存在: {experiment_id}", file=sys.stderr)
        return 1

    # Check if gate_result was already stored
    gate_dict = record.gate_result
    if gate_dict:
        from qp.shared.types import ValidationStatus
        from qp.validation.result import GateDecision, GateResult, RuleResult

        # Reconstruct GateResult from stored dict
        rules = [
            RuleResult(
                rule_name=r["rule_name"],
                status=ValidationStatus(r["status"]),
                score=r["score"],
                threshold=r.get("threshold"),
                actual_value=r.get("actual_value"),
                detail=r.get("detail", ""),
            )
            for r in gate_dict.get("rules", [])
        ]
        gate = GateResult(
            strategy_id=gate_dict["strategy_id"],
            stage=gate_dict["stage"],
            decision=GateDecision(gate_dict["decision"]),
            score=gate_dict["score"],
            confidence=gate_dict["confidence"],
            timestamp=gate_dict.get("timestamp", ""),
            data_integrity=gate_dict.get("data_integrity", "NOT_RUN"),
            factor_validity=gate_dict.get("factor_validity", "NOT_RUN"),
            portfolio_conversion=gate_dict.get("portfolio_conversion", "NOT_RUN"),
            robustness=gate_dict.get("robustness", "NOT_RUN"),
            cost_capacity=gate_dict.get("cost_capacity", "NOT_RUN"),
            rules=rules,
            recommendation=gate_dict.get("recommendation", ""),
            artifacts=gate_dict.get("artifacts", []),
        )
        print(gate.summary())
        return 0

    # No pre-computed gate_result — build one from experiment metrics
    print(f"  Loading experiment: {experiment_id}")
    print(f"  Status: {record.status.value}")
    print("  Gate result not pre-computed — running validation from metrics...")
    print()

    # Build GateResult from experiment metrics
    from qp.shared.types import ValidationStatus
    from qp.validation.result import GateDecision, GateResult, RuleResult

    rules: list[RuleResult] = []
    m = record.metrics

    ic_mean = m.ic_mean
    ic_ir = m.ic_ir
    ic_pass = abs(ic_mean) >= 0.02 and ic_ir >= 0.3

    sharpe = m.sharpe_ratio
    max_dd = abs(m.max_drawdown_pct)

    rules.append(
        RuleResult(
            "rank_ic",
            ValidationStatus.PASS if abs(ic_mean) >= 0.02 else ValidationStatus.FAIL,
            80,
            threshold=0.02,
            actual_value=abs(ic_mean),
            detail=f"|IC|={abs(ic_mean):.4f}",
        )
    )
    rules.append(
        RuleResult(
            "ic_ir",
            ValidationStatus.PASS if ic_ir >= 0.3 else ValidationStatus.FAIL,
            80,
            threshold=0.3,
            actual_value=ic_ir,
            detail=f"IC_IR={ic_ir:.2f}",
        )
    )
    rules.append(
        RuleResult(
            "sharpe",
            ValidationStatus.PASS if sharpe >= 0.5 else ValidationStatus.FAIL,
            80 if sharpe >= 0.5 else 30,
            threshold=0.5,
            actual_value=sharpe,
            detail=f"Sharpe={sharpe:.2f}",
        )
    )
    rules.append(
        RuleResult(
            "max_drawdown",
            ValidationStatus.PASS if max_dd <= 30 else ValidationStatus.FAIL,
            80 if max_dd <= 30 else 30,
            threshold=30,
            actual_value=max_dd,
            detail=f"MaxDD={max_dd:.1f}%",
        )
    )

    gate = GateResult(
        strategy_id=experiment_id,
        stage="backtest_passed",
        decision=GateDecision.PASSED
        if ic_pass and sharpe >= 0.5 and max_dd <= 30
        else GateDecision.BLOCKED,
        score=sum(r.score for r in rules) / len(rules) if rules else 0,
        confidence=sum(1 for r in rules if r.status == ValidationStatus.PASS) / len(rules)
        if rules
        else 0,
        data_integrity="PASS",
        factor_validity="PASS" if ic_pass else "FAIL",
        portfolio_conversion="PASS" if sharpe >= 0.5 and max_dd <= 30 else "FAIL",
        rules=rules,
        recommendation=(f"实验 {experiment_id} 指标通过，可推进到下一阶段。")
        if ic_pass and sharpe >= 0.5 and max_dd <= 30
        else (
            f"实验 {experiment_id} 指标不达标（IC={ic_mean:+.4f}, Sharpe={sharpe:.2f}）。建议归档或修复后重试。"
        ),
    )
    print(gate.summary())
    return 0


def cmd_experiment_clean() -> int:
    """Clean old experiment JSON files, keeping the most recent N."""
    from pathlib import Path

    exp_dir = Path("data/experiments")
    if not exp_dir.exists():
        print("无实验目录 / No experiment directory")
        return 1

    keep = 20
    dry_run = False
    args = sys.argv[3:]
    for a in args:
        if a.startswith("--keep="):
            keep = int(a.split("=", 1)[1])
        elif a == "--dry-run":
            dry_run = True

    files = sorted(exp_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if len(files) <= keep:
        print(f"共 {len(files)} 个文件， ≤ {keep}，无需清理")
        return 0

    to_delete = files[keep:]
    print(f"保留最近 {keep} 个，将删除 {len(to_delete)} 个:")
    for f in to_delete[:10]:
        print(f"  {f.name}")
    if len(to_delete) > 10:
        print(f"  ... 及另外 {len(to_delete) - 10} 个")

    if dry_run:
        print(f"\n[--dry-run] 以上 {len(to_delete)} 个文件将被删除（未实际执行）")
        return 0

    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            deleted += 1
        except OSError as e:
            print(f"  删除失败: {f.name} — {e}", file=sys.stderr)

    print(f"\n已删除 {deleted}/{len(to_delete)} 个旧实验文件")
    return 0
