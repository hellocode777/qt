"""API v1 router — 只读 JSON 端点（供 SPA 原型/外部工具使用）。

设计原则（与原型 qp-proto 对齐，数据同源）：
- 全部只读：读取 qp 运行产物 data/*.json + positions.parquet，不做任何写入。
- 统一入口：路径常量来自 qp.shared.paths；JSON 读取走 qp.shared.json_io。
- 实验净值/调仓重建复用 app.state.experiment_service（ExperimentService 已缓存逻辑，
  不在此重复实现）；其余实验元数据直接读实验目录 json（与数据文件同构）。
- 保留 Jinja2 + HTMX 页面共存：本 router 只新增 /api/v1/* JSON 前缀。

数据真实性约定（WebUI 铁律）：
- 返回的数据均来自磁盘产物自身带的时间戳（updated_at / completed_at 等），
  不做任何默认值伪装；缺失即 None → 前端显示 —。
"""

from __future__ import annotations

import glob
from typing import Any

from fastapi import APIRouter, Query, Request
from loguru import logger

from qp.shared.json_io import json_load
from qp.shared.paths import (
    DATA_DIR,
    DECISIONS_DIR,
    EXPERIMENTS_DIR,
    FACTOR_REGISTRY,
    PAPER_TRADING_DIR,
    POSITIONS_DIR,
    STRATEGY_REGISTRY,
    WATCHDOG_DIR,
)

router = APIRouter(tags=["api_v1"])


@router.get("/api/v1/health")
def health() -> dict[str, Any]:
    """连通性检查。"""
    return {"status": "ok", "data_dir": str(DATA_DIR)}


# 文件名子串（非路径字面量；目录常量统一来自 shared.paths）
_POSITIONS_PARQUET = "positions.parquet"
_ACCOUNT_JSON = "account.json"
_INDEX_JSON = "index.json"
_DP_PREFIX = "dp-*.json"


def _get_exp_svc(request: Request):
    """ExperimentService 已在 lifespan 初始化于 app.state。"""
    svc = getattr(request.app.state, "experiment_service", None)
    if svc is None:
        from qp.web.services.experiment_service import ExperimentService

        svc = ExperimentService()
        request.app.state.experiment_service = svc  # type: ignore[attr-defined]
    return svc


def _as_records(df) -> list[dict[str, Any]]:
    """polars DataFrame → JSON 安全 dicts（Date/None 原生化）。"""
    import polars as pl

    df = df.select(pl.all())
    records = df.to_dicts()
    for r in records:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = str(v)[:10]
    return records


# ─────────────────────────────────────────────────────────────
# 账户 & 持仓
# ─────────────────────────────────────────────────────────────


@router.get("/api/v1/account")
def account() -> dict[str, Any]:
    """账户现金 (account.json) + 持仓汇总 (index.json)。"""
    return {
        "account": json_load(POSITIONS_DIR / _ACCOUNT_JSON),
        "index": json_load(POSITIONS_DIR / _INDEX_JSON),
    }


@router.get("/api/v1/positions")
def positions(active_only: bool = Query(default=False)) -> dict[str, Any]:
    """持仓明细（positions.parquet）。

    market_value 为记录时点市值，非实时行情 —— 前端展示需标注。
    """
    import polars as pl

    path = POSITIONS_DIR / _POSITIONS_PARQUET
    if not path.exists():
        return {"positions": [], "count": 0, "error": "positions.parquet not found"}
    df = pl.read_parquet(str(path))
    if active_only:
        df = df.filter(pl.col("is_active"))
    rows = _as_records(df)
    return {
        "positions": rows,
        "count": len(rows),
        "meta": {"note": "market_value = 记录时点市值，非实时行情"},
    }


# ─────────────────────────────────────────────────────────────
# 模拟盘 & 策略 & 因子
# ─────────────────────────────────────────────────────────────


@router.get("/api/v1/paper")
def paper() -> dict[str, Any]:
    """模拟盘 daily_records 净值序列（paper_trading/*.json）。"""
    items: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(PAPER_TRADING_DIR / "*.json"))):
        d = json_load(p)
        recs = d.get("daily_records") or []
        eq = [r["equity"] for r in recs if "equity" in r]
        ret = (eq[-1] / eq[0] - 1) if len(eq) >= 2 else None
        items.append(
            {
                "strategy_id": d.get("strategy_id"),
                "run_id": d.get("run_id"),
                "capital": d.get("capital"),
                "start_date": d.get("start_date"),
                "created_at": d.get("created_at"),
                "records": recs,
                "n_records": len(recs),
                "total_return_pct": round(ret * 100, 2) if ret is not None else None,
                "latest_equity": round(eq[-1], 2) if eq else None,
            }
        )
    return {"papers": items}


@router.get("/api/v1/strategies")
def strategies() -> dict[str, Any]:
    """策略注册表（strategy_registry.json）概要 + 回测指标。"""
    reg = json_load(STRATEGY_REGISTRY)
    rows: list[dict[str, Any]] = []
    for sid, s in (reg.get("strategies") or {}).items():
        meta = s.get("meta", {})
        rows.append(
            {
                "id": sid,
                "lifecycle": s.get("lifecycle"),
                "active": s.get("active"),
                "approved_at": (s.get("approved") or {}).get("approved_at"),
                "rebalance_frequency": meta.get("rebalance_frequency"),
                "backtest_ic": meta.get("backtest_ic"),
                "backtest_sharpe": meta.get("backtest_sharpe"),
                "backtest_max_dd": meta.get("backtest_max_dd"),
                "backtest_excess_return": meta.get("backtest_excess_return"),
                "weights": meta.get("weights"),
                "parameters": meta.get("parameters"),
                "owner": meta.get("owner"),
                "raw": s,
            }
        )
    return {"strategies": rows, "count": len(rows)}


@router.get("/api/v1/factors")
def factors() -> dict[str, Any]:
    """因子注册表（factor_registry.json）。"""
    fr = json_load(FACTOR_REGISTRY)
    items: list[dict[str, Any]] = []
    for name, f in (fr.get("factors") or {}).items():
        items.append(
            {
                "name": f.get("name") or name,
                "class": f.get("class"),
                "version": f.get("version"),
                "category": f.get("category"),
                "lookback": f.get("lookback"),
                "direction": f.get("direction"),
                "author": f.get("author"),
                "description": f.get("description"),
                "required_data": f.get("required_data"),
                "registered_at": f.get("registered_at"),
            }
        )
    return {
        "factors": items,
        "n_factors": fr.get("n_factors"),
        "updated_at": fr.get("updated_at"),
    }


# ─────────────────────────────────────────────────────────────
# 决策包
# ─────────────────────────────────────────────────────────────


@router.get("/api/v1/regime")
def regime() -> dict[str, Any]:
    """最新决策包的市场状态 + 人工复核状态。"""
    dps = sorted(glob.glob(str(DECISIONS_DIR / _DP_PREFIX)))
    if not dps:
        return {"regime": None}
    d = json_load(dps[-1])
    return {
        "package_id": d.get("package_id"),
        "date": d.get("date"),
        "regime": d.get("regime"),
        "signals": d.get("strategy", {}).get("signals"),
        "risk_audit": d.get("risk_audit"),
        "human_review": d.get("human_review"),
    }


@router.get("/api/v1/decisions")
def decisions() -> dict[str, Any]:
    """决策包列表（data/decisions/dp-*.json，倒序）。"""
    dps = sorted(glob.glob(str(DECISIONS_DIR / _DP_PREFIX)), reverse=True)
    items: list[dict[str, Any]] = []
    for p in dps:
        d = json_load(p)
        hr = d.get("human_review", {})
        items.append(
            {
                "package_id": d.get("package_id"),
                "date": d.get("date"),
                "generated_at": d.get("generated_at"),
                "regime": d.get("regime", {}).get("regime"),
                "regime_confidence": d.get("regime", {}).get("confidence"),
                "signals": d.get("strategy", {}).get("signals"),
                "passed": (d.get("risk_audit") or {}).get("passed"),
                "candidate_weights": d.get("risk_audit", {}).get("candidate_weights"),
                "reviewed": hr.get("reviewed"),
                "executed": hr.get("executed"),
                "status": hr.get("status"),
                "execution_time": hr.get("execution_time"),
            }
        )
    return {"decisions": items, "count": len(items)}


@router.get("/api/v1/decisions/{package_id}")
def decision_detail(package_id: str) -> dict[str, Any]:
    """单个决策包全文。"""
    p = DECISIONS_DIR / f"{package_id}.json"
    if not p.exists():
        return {"error": f"决策包不存在: {package_id}"}
    return json_load(p)


# ─────────────────────────────────────────────────────────────
# 回测实验
# ─────────────────────────────────────────────────────────────

_METRIC_KEYS = (
    "ic_mean",
    "ic_ir",
    "ic_t_stat",
    "sharpe_ratio",
    "max_drawdown_pct",
    "excess_return_pct",
    "annual_return_pct",
    "total_return_pct",
    "turnover_pct",
    "final_equity",
    "n_days",
    "in_sample_ic",
    "out_of_sample_ic",
)


@router.get("/api/v1/experiments")
def experiments() -> dict[str, Any]:
    """回测实验列表（experiments/*.json，倒序，含关键指标概要）。"""
    files = sorted(glob.glob(str(EXPERIMENTS_DIR / "*.json")), reverse=True)
    items: list[dict[str, Any]] = []
    for p in files:
        try:
            d: dict[str, Any] = json_load(p)
        except Exception as exc:
            logger.warning("skip unreadable experiment json {}: {}", p, exc)
            continue
        cfg = d.get("config", {}) or {}
        met = d.get("metrics", {}) or {}
        eid = d.get("experiment_id") or p.split("/")[-1].removesuffix(".json")
        nav_path = EXPERIMENTS_DIR / eid / "daily_nav.parquet"
        items.append(
            {
                "experiment_id": eid,
                "status": d.get("status"),
                "created_at": d.get("created_at"),
                "completed_at": d.get("completed_at"),
                "description": cfg.get("description"),
                "strategy_name": cfg.get("strategy_name"),
                "features": cfg.get("features"),
                "dataset_version": cfg.get("dataset_version"),
                "has_nav": nav_path.exists(),
                "metrics": {k: met.get(k) for k in _METRIC_KEYS},
            }
        )
    return {"experiments": items, "count": len(items)}


@router.get("/api/v1/experiments/{experiment_id}")
def experiment_detail(experiment_id: str) -> dict[str, Any]:
    """单个实验 json 全文（config + metrics + lineage + gate_result）。"""
    p = EXPERIMENTS_DIR / f"{experiment_id}.json"
    if not p.exists():
        return {"error": f"实验不存在: {experiment_id}"}
    return json_load(p)


@router.get("/api/v1/experiments/{experiment_id}/nav")
def experiment_nav(request: Request, experiment_id: str) -> dict[str, Any]:
    """净值曲线（daily_nav.parquet）——复用 ExperimentService 列选择逻辑。"""
    return _get_exp_svc(request).get_equity_curve(experiment_id)


@router.get("/api/v1/experiments/{experiment_id}/trades")
def experiment_trades(request: Request, experiment_id: str) -> dict[str, Any]:
    """调仓重建（trade_events.json，无缓存时由 ExperimentService 现算）。"""
    return _get_exp_svc(request).get_trade_reconstruction(experiment_id)


# ─────────────────────────────────────────────────────────────
# 健康监控（因子/策略/系统状态/watchdog 心跳）
# 复用 HTML 页同一服务层（FactorHealthService/HealthService），口径一致。
# ─────────────────────────────────────────────────────────────


def _get_factor_health_svc(request: Request):
    """FactorHealthService 懒加载（与 /health HTML 页同源）。"""
    svc = getattr(request.app.state, "factor_health_service", None)
    if svc is None:
        from qp.web.services.factor_health_service import FactorHealthService

        svc = FactorHealthService()
        request.app.state.factor_health_service = svc  # type: ignore[attr-defined]
    return svc


def _get_health_svc(request: Request):
    """HealthService 懒加载（与 /health HTML 页同源）。"""
    svc = getattr(request.app.state, "health_service", None)
    if svc is None:
        from qp.web.services.health_service import HealthService

        svc = HealthService()
        request.app.state.health_service = svc  # type: ignore[attr-defined]
    return svc


@router.get("/api/v1/health/factors")
def health_factors(request: Request) -> dict[str, Any]:
    """因子健康总览（factor_health.parquet → 服务层聚合口径，含推荐动作）。"""
    return _get_factor_health_svc(request).overview()


@router.get("/api/v1/health/factors/{factor_name}")
def health_factor_detail(
    request: Request, factor_name: str, days: int = Query(default=252, ge=30, le=1000)
) -> dict[str, Any]:
    """单因子健康详情 + IC 曲线序列（factor_health_service.factor_detail 口径）。"""
    return _get_factor_health_svc(request).factor_detail(factor_name, days=days)


@router.get("/api/v1/health/strategies")
def health_strategies(request: Request) -> dict[str, Any]:
    """策略健康列表（strategy_health.parquet 最新 + 趋势 + alerts）。"""
    return {"strategies": _get_health_svc(request).strategy_health_list()}


# watchdog job 期望频率 —— 镜像 scheduler.py add_job 的 CronTrigger 注册
# （mon-fri HH:MM，UTC+8）。仅 UI 展示参考，非执行依据；执行频率以 scheduler 代码为准。
_WATCHDOG_EXPECTED = {
    "monitor_check": "工作日 09:07",
    "retrain_notify": "工作日 09:17",
    "pre_close_check": "工作日 16:53",
    "daily_pipeline": "工作日 18:00",
    "email_report": "工作日 18:30",
    "paper_trading": "工作日 18:32",
}


def _watchdog_pings() -> list[dict[str, Any]]:
    """data/monitoring/watchdog/*.ping → 心跳时间 + 距今小时数。

    ping 文件内容即 UTC ISO 时间；解析失败回退文件 mtime。缺失心跳的
    job 仍按 _WATCHDOG_EXPECTED 列出（has_ping=false），便于暴露
    pre_close_check 之类被跳过/未注册的异常。
    """
    from datetime import datetime

    from qp.shared.time import now_utc

    now = now_utc()
    out: list[dict[str, Any]] = []
    for name, expected in _WATCHDOG_EXPECTED.items():
        p = WATCHDOG_DIR / f"{name}.ping"
        has_ping = p.exists()
        last: datetime | None = None
        if has_ping:
            try:
                raw = p.read_text(encoding="utf-8").strip()
                last = datetime.fromisoformat(raw)
            except Exception:
                last = datetime.fromtimestamp(p.stat().st_mtime, tz=now.tzinfo)
        out.append(
            {
                "name": name,
                "expected": expected,
                "has_ping": has_ping,
                "last_ping": last.isoformat() if last is not None else None,
                "age_hours": round((now - last).total_seconds() / 3600, 2)
                if last is not None
                else None,
            }
        )
    return out


@router.get("/api/v1/system-health")
def system_health(request: Request) -> dict[str, Any]:
    """系统状态 + 最近健康日志 + watchdog 心跳（运维雷达一页）。"""
    svc = _get_health_svc(request)
    return {
        "system_state": svc.system_state(),
        "latest_health": svc.latest_health(),
        "history": svc.health_history(limit=30),
        "watchdog": _watchdog_pings(),
    }
