"""CLI command handlers for the "monitor" group."""

from __future__ import annotations


def cmd_monitor_check() -> int:
    """Run full KillSwitchPipeline — regime + drift + decay + kill switch + health."""
    from datetime import datetime

    from qp.monitoring.kill_switch_pipeline import KillSwitchPipeline, MonitorAction
    from qp.platform.pipeline.context import PipelineContext

    print("=== QP 监控检查 / Monitor Check ===")
    print(f"  时间 / Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    ctx = PipelineContext(pipeline_name="cli_monitor_check")
    pipeline = KillSwitchPipeline()
    result = pipeline.run(ctx)

    if result.status.value != "success":
        print(f"\n❌ 检查失败: {result.errors}")
        return 1

    report = result.metadata.get("report")  # type: ignore[union-attr]
    if report is None:
        print("\n❌ 无健康报告")
        return 1

    print()
    print("── 市场状态 / Market Regime ──")
    if report.regime:
        print(f"  状态 / Regime:     {report.regime.regime.value}")
        print(f"  置信度 / Confidence: {report.regime.confidence:.0%}")
        print(f"  趋势强度 / ADX:    {report.regime.trend_strength:.1f}")
        print(f"  涨跌停比 / LUD:    {report.regime.limit_up_down_ratio:.3f}")
        print(f"  行业轮动 / Rot:    {report.regime.sector_rotation_speed:.3f}")
        print(f"  危机模式:          {'是' if report.regime.is_crisis else '否'}")
    else:
        print("  ⚠ 无市场数据")

    print()
    print("── 熔断检查 / Kill Switch ──")
    icon = "🚨" if report.kill_switch_triggered else "✅"
    status = "触发!" if report.kill_switch_triggered else "正常"
    print(f"  {icon} 状态: {status}")
    ks_result = getattr(report, "_ks_result", None)
    level = "NORMAL"
    if ks_result:
        level = str(ks_result.get("level", "NORMAL"))
    print(f"  熔断级别:          {level}")
    if report.kill_switch_triggers:
        for t in report.kill_switch_triggers:
            print(f"    ⚠ {t}")

    print()
    print("── 特征漂移 / Drift ──")
    print(
        f"  PSI:               {report.psi_value:.3f}"
        + (" ⚠" if report.psi_value >= 0.25 else "")
    )

    print()
    print("── 模型衰减 / Model Decay ──")
    print(f"  状态:              {report.model_decay_stage}")

    print()
    print("── 策略健康 / Strategy Health ──")
    if report.strategy_health:
        print(f"  分数:              {report.strategy_health.health_score:.0f}/100")
        print(
            f"  等级:              {report.strategy_health.health_level.value.upper()}"
        )

    print()
    print("── 建议操作 / Action ──")
    action_icons = {
        MonitorAction.OK: "✅",
        MonitorAction.WATCH: "👀",
        MonitorAction.PAUSE_BUY: "⛔",
        MonitorAction.REDUCE: "🔻",
        MonitorAction.STOP: "🚨",
    }
    print(f"  {action_icons.get(report.action, '❓')} {report.action.value.upper()}")

    if report.alerts:
        print()
        print("── 告警 / Alerts ──")
        for a in report.alerts[:10]:
            print(f"  - {a}")

    print()
    return 0 if report.action == MonitorAction.OK else 1


def cmd_monitor_regime() -> int:
    """Detect current market regime."""
    from pathlib import Path

    import polars as pl

    from qp.monitoring.regime import MarketRegimeEngine

    print("=== QP 市场状态检测 / Market Regime Detection ===")
    print()

    data_dir = Path("data/dataset")
    parquet_files = sorted(data_dir.glob("daily_price_*.parquet"))
    if not parquet_files:
        print("❌ 未找到数据文件 / No data found. 请先运行 qp run daily")
        return 1

    prices = pl.read_parquet(str(parquet_files[-1]))
    engine = MarketRegimeEngine()
    result = engine.classify(prices)

    direction_map = {1: "上升 (Uptrend)", -1: "下降 (Downtrend)", 0: "中性 (Neutral)"}

    print(f"  市场状态 / Regime:      {result.regime.value}")
    print(f"  置信度 / Confidence:    {result.confidence:.0%}")
    print(f"  趋势强度 / ADX:         {result.trend_strength:.1f}")
    print(f"  趋势方向 / Direction:   {direction_map.get(result.trend_direction)}")
    print(f"  年化波动率 / Ann. Vol:  {result.annualized_vol:.1%}")
    print(f"  波动率分位数 / Vol%:    {result.volatility_percentile:.0f}%")
    print()

    if result.is_trending:
        print("  💡 建议：趋势市场 → 动量策略 / Use momentum strategies")
    elif result.regime.value == "RANGING":
        print("  💡 建议：震荡市场 → 均值回归策略 / Use mean-reversion strategies")
    elif result.regime.value == "HIGH_VOL":
        print("  💡 建议：高波动 → 降低仓位 / Reduce position sizes")

    return 0


def cmd_monitor_alert_test() -> int:
    """Send test alerts to all configured channels."""
    from qp.monitoring.alerts import (
        AlertManager,
        AlertSeverity,
        LogAlert,
        TelegramAlert,
        TerminalAlert,
    )

    print("=== QP 告警测试 / Alert Test ===")
    print()

    manager = AlertManager()
    manager.add_channel(TerminalAlert(use_colors=True))
    manager.add_channel(LogAlert())
    manager.add_channel(TelegramAlert(), min_severity=AlertSeverity.WARNING)

    print(f"  已注册通道 / Channels: {manager.channel_count}")
    print()

    print("  发送 INFO 级别...")
    manager.info(
        "测试信息 / Test Info",
        "监控系统正常运行。All systems operational.",
        "alert_test",
    )

    print("  发送 WARNING 级别...")
    manager.warning(
        "测试警告 / Test Warning",
        "这是一条警告测试。This is a test warning.",
        "alert_test",
    )

    print("  发送 CRITICAL 级别...")
    manager.critical(
        "测试严重告警 / Test Critical",
        "这是一条严重告警测试。This is a test critical alert.",
        "alert_test",
    )

    print()
    print("  告警测试完成 / Alert test complete.")
    return 0
