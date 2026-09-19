"""API v1 router — SPA 数据端点（读 qp 运行产物）+ 人工复核动作端点。

设计原则（与原型 qp-proto 对齐，数据同源）：
- 读取全部只读：读取 qp 运行产物 data/*.json + *.parquet，不做任何写入。
- 统一入口：路径常量来自 qp.shared.paths；JSON 读取走 qp.shared.json_io。
- 实验净值/调仓重建复用 app.state.experiment_service（ExperimentService 已缓存逻辑，
  不在此重复实现）；其余实验元数据直接读实验目录 json（与数据文件同构）。
- 保留 Jinja2 + HTMX 页面共存：本 router 只新增 /api/v1/* JSON 前缀。
- 人工复核动作（/review /execute /close，POST JSON）：与老 UI HTML 表单同语义，
  委托 DecisionService 状态机；approve 默认 create_positions=True（按决策包建仓/平仓）。

数据真实性约定（WebUI 铁律）：
- 返回的数据均来自磁盘产物自身带的时间戳（updated_at / completed_at 等），
  不做任何默认值伪装；缺失即 None → 前端显示 —。
"""

from __future__ import annotations

import glob
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Query, Request
from loguru import logger

from qp.shared.json_io import json_load
from qp.shared.paths import (
    DAILY_PRICE_LATEST,
    DATA_DIR,
    DECISIONS_DIR,
    EXPERIMENTS_DIR,
    FACTOR_REGISTRY,
    INDUSTRY_HEAT_DIR,
    KNOWLEDGE_DIR,
    PAPER_TRADING_DIR,
    PORTFOLIO_DIR,
    POSITIONS_DIR,
    REPORTS_DIR,
    SIMULATION_DIR,
    STOCK_NAMES,
    STRATEGY_REGISTRY,
    WATCHDOG_DIR,
)
from qp.web.services.position_service import PositionService

router = APIRouter(tags=["api_v1"])


@router.get("/api/v1/industry-heat")
def industry_heat(
    source: str = Query(default="", description="price | capital_flow（空 = 最新快照）"),
    limit: int = Query(default=40, ge=1, le=200),
) -> dict[str, Any]:
    """行业热度快照（阶段 1 落盘产物，由 `qp industry heat --save` 生成）。

    **如实标注**：``as_of`` 是快照真正覆盖到的数据日、``requested_as_of`` 是请求日、
    ``data_date_max`` 是底层价格数据的最末日，并给出 ``lag_days`` / ``data_lag_days``
    两个滞后天数；无快照或读取失败 → ``{ok: False, error: ...}``，**不伪造空排行**
    （WebUI 铁律：默认值不得伪装成测量值）。

    文件名约定：``YYYY-MM-DD_price.json``（价格源）/ ``YYYY-MM-DD.json``（资金流源）。
    """
    from datetime import date as _date

    from qp.shared.time import fmt_date

    files = sorted(INDUSTRY_HEAT_DIR.glob("*.json")) if INDUSTRY_HEAT_DIR.is_dir() else []
    if source == "price":
        files = [f for f in files if f.stem.endswith("_price")]
    elif source == "capital_flow":
        files = [f for f in files if not f.stem.endswith("_price")]
    if not files:
        return {
            "ok": False,
            "error": "no industry-heat snapshot",
            "hint": "生成: qp industry heat --save [--source price|capital_flow]",
            "dir": str(INDUSTRY_HEAT_DIR),
            "available": [],
        }

    latest = files[-1]
    try:
        payload = json_load(latest)
    except Exception as exc:
        logger.warning("industry-heat 快照读取失败 {}: {}", latest.name, exc)
        return {"ok": False, "error": f"snapshot unreadable: {exc}", "file": latest.name}

    as_of = str(payload.get("as_of") or "")
    data_max = str(payload.get("data_date_max") or "")
    today = _date.fromisoformat(fmt_date())

    def _lag(day: str) -> int | None:
        try:
            return (today - _date.fromisoformat(day)).days
        except ValueError:
            return None

    industries = list(payload.get("industries") or [])
    return {
        "ok": True,
        "snapshot_file": latest.name,
        "source": payload.get("source"),
        "window": payload.get("window"),
        "granularity": payload.get("granularity"),
        "as_of": as_of or None,
        "requested_as_of": payload.get("requested_as_of"),
        "data_date_min": payload.get("data_date_min"),
        "data_date_max": data_max or None,
        "lag_days": _lag(as_of) if as_of else None,
        "data_lag_days": _lag(data_max) if data_max else None,
        "n_industries": len(industries),
        "other_members": payload.get("other_members"),
        "rows": industries[:limit],
        "available_snapshots": [f.name for f in sorted(INDUSTRY_HEAT_DIR.glob("*.json"))],
    }


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


def _json_or_empty(path: Any) -> dict[str, Any]:
    """读 JSON；文件缺失/损坏/非 dict → ``{}``（只读端点降级，不 500）。

    ``json_load`` 直接抛 FileNotFoundError —— 运行产物（account.json / registry 等）
    在新机器或首次运行前并不存在，前端应看到空数据（显示 —），而不是整页 500。
    """
    try:
        if not path.exists():
            return {}
        data = json_load(path)
    except Exception as exc:
        logger.warning("json unavailable ({}): {}", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/api/v1/account")
def account() -> dict[str, Any]:
    """账户现金 (account.json) + 持仓汇总 (index.json) + 统一估值三口径 (valuation)。

    ``index.json.active_value`` 是**成本市值**（记录时点，非实时）—— 与页面按最新收盘
    标记的市值不同源，故这里额外给出 ``valuation``：成本口径 / 最新收盘口径 / 费用后。
    前端一律消费 ``valuation``，不要自己拿 cash+市值重算（否则同一页面会出现两个"总权益"）。
    """
    import polars as pl

    acct = _json_or_empty(POSITIONS_DIR / _ACCOUNT_JSON)
    cash = float(acct.get("cash", 0.0) or 0.0)

    valuation: dict[str, Any] = {}
    try:
        path = POSITIONS_DIR / _POSITIONS_PARQUET
        rows = _as_records(pl.read_parquet(str(path))) if path.exists() else []
        svc = PositionService(quote_path=DAILY_PRICE_LATEST)
        valuation = svc.account_views(cash=cash, rows=svc.enrich(rows))
    except Exception as exc:
        logger.warning("account valuation unavailable: {}", exc)
        valuation = {"error": "valuation unavailable"}

    return {
        "account": acct,
        "index": _json_or_empty(POSITIONS_DIR / _INDEX_JSON),
        "valuation": valuation,
    }


@router.get("/api/v1/positions")
def positions(active_only: bool = Query(default=False)) -> dict[str, Any]:
    """持仓明细（positions.parquet）+ 最新收盘标记 + 费用后盈亏。

    字段语义（三套口径，勿混用；统一实现在 qp.web.services.position_service）：
    - 记录时点/已实现：``market_value``=成本市值(entry×shares)；``pnl``/``pnl_pct`` 是
      **已实现盈亏**（仅平仓时结算，持仓中恒 0）—— 持仓行展示必须用标记值，别把 0 当盈亏。
    - 标记（最新收盘）：``latest_price`` / ``quote_date`` / ``latest_suspended`` /
      ``market_value_latest`` / ``unrealized_pnl(_pct)``（**小数**：0.1333 = +13.33%）。
    - 费用后（估算）：``est_buy_fee`` / ``est_sell_fee`` / ``est_round_trip_fee`` /
      ``unrealized_pnl_net(_pct)``（活跃行）、``realized_pnl_net(_pct)``（已平仓行）；
      费率见 ``meta.fees``，未含券商最低佣金/过户费/市场冲击。
    无行情（停牌/退市/数据缺失）→ ``None``，前端显示 —，不得回落为 0。
    """
    import polars as pl

    path = POSITIONS_DIR / _POSITIONS_PARQUET
    if not path.exists():
        return {"positions": [], "count": 0, "error": "positions.parquet not found"}
    df = pl.read_parquet(str(path))
    if active_only:
        df = df.filter(pl.col("is_active"))
    svc = PositionService(quote_path=DAILY_PRICE_LATEST)
    rows = svc.enrich(_as_records(df))
    return {
        "positions": rows,
        "count": len(rows),
        "quote_date": svc.quotes()["quote_date"],
        "meta": {
            "note": "market_value/pnl = 记录时点值(已实现，平仓结算)；latest_price/unrealized_* = 最新收盘标记；*_net = 估算费用后",
            "fees": svc.cost_rates(),
        },
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
    reg = _json_or_empty(STRATEGY_REGISTRY)
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
    fr = _json_or_empty(FACTOR_REGISTRY)
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


# ─────────────────────────────────────────────────────────────
# 影子盘 / 组合净值 / 数据质量 / 股票搜索
# ─────────────────────────────────────────────────────────────

_SHADOW_DAILY_PARQUET = "shadow_daily.parquet"
_SHADOW_POSITIONS_PARQUET = "shadow_positions.parquet"
_NAV_HISTORY_PARQUET = "nav_history.parquet"


@router.get("/api/v1/simulation")
def simulation() -> dict[str, Any]:
    """影子盘（simulation/）：ShadowLedger 摘要 + 日度净值 + 持仓/已平仓交易。

    与模拟盘 paper 的区别：shadow 是候选/实验策略暗跑，paper 是已上策略跟跑。
    """
    import polars as pl

    from qp.simulation.shadow_ledger import ShadowLedger

    ledger = ShadowLedger()
    summary = ledger.summary()
    positions: list[dict[str, Any]] = []
    pos_path = SIMULATION_DIR / _SHADOW_POSITIONS_PARQUET
    if pos_path.exists():
        df = pl.read_parquet(str(pos_path)).sort("entry_date")
        positions = df.to_dicts()
    return {"summary": summary, "positions": positions}


@router.get("/api/v1/portfolio")
def portfolio() -> dict[str, Any]:
    """组合净值（portfolio/nav_history.parquet）：total_nav vs benchmark + 基础统计。"""
    import polars as pl

    p = PORTFOLIO_DIR / _NAV_HISTORY_PARQUET
    if not p.exists():
        return {"records": [], "count": 0}
    df = pl.read_parquet(str(p)).sort("date")
    records = []
    for r in df.to_dicts():
        records.append(
            {
                "date": str(r.get("date"))[:10],
                "total_nav": r.get("total_nav"),
                "cash": r.get("cash"),
                "positions_value": r.get("positions_value"),
                "benchmark_value": r.get("benchmark_value"),
                "n_positions": r.get("n_positions"),
                "decision_id": r.get("decision_id") or "",
            }
        )
    navs = [r["total_nav"] for r in records if r["total_nav"] is not None]
    latest = navs[-1] if navs else None
    first = navs[0] if navs else None
    return {
        "records": records,
        "count": len(records),
        "stats": {
            "latest_nav": latest,
            "total_return_pct": round((latest / first - 1) * 100, 2)
            if latest is not None and first
            else None,
            "n_days": len(records),
        },
    }


@router.get("/api/v1/data-quality")
def data_quality() -> dict[str, Any]:
    """数据质量报告时间线（reports/data_quality_*.json，按日期升序）。"""
    files = sorted(glob.glob(str(REPORTS_DIR / "data_quality_*.json")))
    items: list[dict[str, Any]] = []
    for p in files:
        try:
            d = json_load(p)
        except Exception:
            continue
        items.append(
            {
                "date": p.rsplit("/", 1)[-1].removeprefix("data_quality_").removesuffix(".json"),
                "status": d.get("status"),
                "timestamp": d.get("timestamp"),
                "checks": d.get("checks"),
                "rows_after": d.get("rows_after"),
                "new_rows": d.get("new_rows"),
                "symbols": d.get("symbols"),
                "sha256": d.get("sha256"),
                "pipeline_run_id": d.get("pipeline_run_id"),
            }
        )
    return {"reports": items, "count": len(items)}


@lru_cache(maxsize=1)
def _stock_names_cached() -> dict[str, str]:
    """stock_names.json 全量缓存（代码 → 名称）。"""
    return _json_or_empty(STOCK_NAMES)


@router.get("/api/v1/stocks/search")
def stock_search(q: str = Query(default="", min_length=1, max_length=20)) -> dict[str, Any]:
    """A 股名录搜索：代码前缀 或 名称包含（stock_names.json, {n} 只）。"""
    names = _stock_names_cached()
    needle = q.strip().lower()
    if not needle:
        return {"results": []}
    out: list[dict[str, str]] = []
    for code, name in names.items():
        if code.startswith(needle) or needle in str(name).lower():
            out.append({"code": code, "name": name})
        if len(out) >= 20:
            break
    return {"results": out, "count": len(out), "needle": q.strip()}


# ─────────────────────────────────────────────────────────────
# 知识库（knowledge/*.md 复盘/失败分析/研究债务）
# ─────────────────────────────────────────────────────────────

_KNOWLEDGE_MAX_PER_CATEGORY = 40


def _md_frontmatter(path) -> dict[str, Any]:
    """解析 md 前导 frontmatter（--- yaml ---）；无则空 dict。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    try:
        import yaml

        d = yaml.safe_load(text[3:end].strip())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _knowledge_index() -> list[dict[str, Any]]:
    """全量知识 md 索引（含 frontmatter title/tags）。文件 1700+，缓存一次。"""
    items: list[dict[str, Any]] = []
    for p in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        meta = _md_frontmatter(p)
        rel = str(p.relative_to(KNOWLEDGE_DIR))
        parts = rel.split("/")
        items.append(
            {
                "category": parts[0] if len(parts) > 1 else "_root",
                "rel": rel,
                "name": p.stem,
                "title": meta.get("title") or p.stem,
                "created_at": meta.get("created_at"),
                "tags": meta.get("tags") or [],
                "size": p.stat().st_size,
            }
        )
    return items


@router.get("/api/v1/knowledge")
def knowledge() -> dict[str, Any]:
    """知识库索引（按类别聚合，倒序截断；research_debt 量大只取最近）。"""
    items = _knowledge_index()
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    cats: list[dict[str, Any]] = []
    for cat in sorted(by_cat, key=lambda c: (c == "_root", c)):
        arr = by_cat[cat]
        # 按 created_at 倒序（无时间戳的排最后）
        arr.sort(key=lambda x: x["created_at"] or "", reverse=True)
        total = len(arr)
        shown = arr[:_KNOWLEDGE_MAX_PER_CATEGORY]
        cats.append(
            {
                "category": cat,
                "total": total,
                "shown": len(shown),
                "truncated": total > len(shown),
                "items": shown,
            }
        )
    return {"categories": cats, "total": len(items)}


@router.get("/api/v1/knowledge/content")
def knowledge_content(path: str = Query(...)) -> dict[str, Any]:
    """md 原文（剥离 frontmatter）。path 相对 data/knowledge，防目录穿越。"""
    base = KNOWLEDGE_DIR.resolve()
    p = (KNOWLEDGE_DIR / path).resolve()
    if p.suffix != ".md" or not str(p).startswith(str(base)) or not p.exists():
        return {"error": f"知识文件不存在或非法路径: {path}"}
    text = p.read_text(encoding="utf-8", errors="ignore")
    meta = _md_frontmatter(p)
    if text.startswith("---"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4 :].lstrip("\n")
    return {"rel": path, "meta": meta, "content": text, "size": p.stat().st_size}


# ─────────────────────────────────────────────────────────────
# 决策包人工复核动作（POST JSON — 与老 UI HTML 表单同语义）
# ─────────────────────────────────────────────────────────────


def _get_decision_svc(request: Request):
    """DecisionService 懒加载（复用 HTML 页 app.state 实例）。"""
    svc = getattr(request.app.state, "decision_service", None)
    if svc is None:
        from qp.web.services.decision_service import DecisionService

        svc = DecisionService()
        request.app.state.decision_service = svc  # type: ignore[attr-defined]
    return svc


def _action_result(package_id: str, result: dict[str, Any] | None) -> dict[str, Any]:
    """动作结果统一：失败给原因，成功回读最新状态。"""
    if result is None:
        return {"ok": False, "package_id": package_id, "error": "无效状态流转或决策包不存在"}
    from qp.web.services.decision_service import DecisionService

    svc = DecisionService()
    return {"ok": True, "package_id": package_id, "detail": svc.get_by_id(package_id)}


async def _read_body(request: Request) -> dict[str, Any]:
    """POST JSON body 读取（无/非法 body → 空 dict）。"""
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


@router.post("/api/v1/decisions/{package_id}/review")
async def decision_review(request: Request, package_id: str) -> dict[str, Any]:
    """人工复核: approve / reject / modify。

    ⚠️ approve 默认 create_positions=True：按决策包 SELL 平仓 + BUY 建仓
    （PositionLedger 写 data/positions + account）。与老 UI 同语义，请前端强确认。
    """
    svc = _get_decision_svc(request)
    body = await _read_body(request)
    action = (body.get("action") or "approve").lower()
    notes = body.get("notes") or ""
    if action == "reject":
        result = svc.reject(package_id, reviewer="webui-spa", notes=notes)
    elif action == "modify":
        result = svc.modify(package_id, reviewer="webui-spa", notes=notes)
    else:
        result = svc.approve(package_id, reviewer="webui-spa", notes=notes)
    return _action_result(package_id, result)


@router.post("/api/v1/decisions/{package_id}/execute")
async def decision_execute(request: Request, package_id: str) -> dict[str, Any]:
    """标记已执行（APPROVED → PARTIALLY_EXECUTED → MONITORING）。仅状态流转。"""
    svc = _get_decision_svc(request)
    body = await _read_body(request)
    result = svc.mark_executed(package_id, notes=body.get("notes") or "")
    return _action_result(package_id, result)


@router.post("/api/v1/decisions/{package_id}/close")
async def decision_close(request: Request, package_id: str) -> dict[str, Any]:
    """关闭决策（MONITORING → CLOSED，终态）。仅状态流转。"""
    svc = _get_decision_svc(request)
    body = await _read_body(request)
    result = svc.close(package_id, notes=body.get("notes") or "")
    return _action_result(package_id, result)
