"""审批守卫（Strategy Approval Guard）——Validation Gate 的强制关卡。

宪法依据：`docs/constitution/rule.md` §5「Validation Gate —— 策略上生产前的强制审查关卡」
与 §5.1「策略生命周期」。生产切换必须留痕、必须过门禁，不能靠调用方的自觉。

2026-10-28 事故背景：一次 `qp strategy approve` 把生产从 `lvr_vol_only` 切到了
`momentum_vol_full`（B 组），而该策略最近一次质量门禁是 `decision=research_only`、
`portfolio_conversion=FAIL`、`robustness=NOT_RUN`，`approved_by` 还是空字符串。
`StrategyRegistry.approve()` 当时只做「把 meta 原样冻结」，不校验任何门槛。

硬拦（blocking，需 `force=True` 才能越过）：
  1. `approved_by` 为空 —— 审计上必须知道谁批的
  2. 最新门禁 `decision` 不在允许集合内（如 `research_only`）
  3. `data_integrity` / `factor_validity` / `portfolio_conversion` 不为 PASS

仅警告（advisory，不阻断）：
  4. `robustness` / `cost_capacity` 未跑或未过
  5. 完全找不到门禁记录（研究期策略常见；允许发布但提示补跑）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from qp.shared.json_io import json_load
from qp.shared.paths import EXPERIMENTS_DIR

# 门禁放行的 decision 取值（研究门禁通过时会写这些；`research_only` 等一律拒绝）
ALLOWED_GATE_DECISIONS: frozenset[str] = frozenset({"proceed", "approved", "pass", "go"})

# 必须为 PASS 才能上生产的检查项
REQUIRED_GATE_CHECKS: tuple[str, ...] = (
    "data_integrity",
    "factor_validity",
    "portfolio_conversion",
)

# 只告警、不阻断的检查项
ADVISORY_GATE_CHECKS: tuple[str, ...] = ("robustness", "cost_capacity")


@dataclass(frozen=True)
class ApprovalIssue:
    """一条审批检查结果。"""

    code: str
    message: str
    blocking: bool


class ApprovalBlockedError(ValueError):
    """审批被守卫拦截。

    继承 ``ValueError``：既有 ``except ValueError`` 的调用方（CLI / WebUI）
    无需改动即可捕获，同时保留结构化的 ``issues`` 供上层逐条展示。
    """

    def __init__(self, strategy_id: str, issues: list[ApprovalIssue]) -> None:
        self.strategy_id = strategy_id
        self.issues = issues
        blocking = [issue for issue in issues if issue.blocking]
        detail = "；".join(f"[{issue.code}] {issue.message}" for issue in blocking)
        super().__init__(f"策略 {strategy_id} 审批被拒绝：{detail}")


def latest_gate(strategy_id: str, search_dir: Path | None = None) -> dict[str, Any] | None:
    """返回该策略最新的一条质量门禁记录；没有则返回 ``None``。

    门禁文件命名约定：``<strategy_id>_<timestamp>_gate.json``，位于
    ``data/experiments/``。排序优先用记录内的 ``timestamp`` 字段，缺失时退回
    文件 mtime —— 不假设文件名字典序等于时间序。
    """
    directory = Path(search_dir) if search_dir is not None else Path(EXPERIMENTS_DIR)
    best_key: tuple[str, float] = ("", -1.0)
    best_record: dict[str, Any] | None = None

    for path in sorted(directory.glob(f"{strategy_id}_*_gate.json")):
        try:
            record = json_load(path)
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if not isinstance(record, dict):
            continue
        key = (str(record.get("timestamp", "")), mtime)
        if key > best_key:
            best_key = key
            best_record = record
    return best_record


def evaluate_approval(
    strategy_id: str,
    approved_by: str,
    gate: dict[str, Any] | None,
) -> list[ApprovalIssue]:
    """按硬拦/告警规则评估一次审批，返回全部 issues（不抛异常）。"""
    issues: list[ApprovalIssue] = []

    if not approved_by.strip():
        issues.append(
            ApprovalIssue(
                code="MISSING_APPROVER",
                message="approved_by 为空：审批必须记录批准人（qp strategy approve <id> --by <姓名>）",
                blocking=True,
            )
        )

    if gate is None:
        issues.append(
            ApprovalIssue(
                code="NO_GATE_RECORD",
                message="未找到该策略的质量门禁记录；允许发布，但建议先跑质量门禁并留痕",
                blocking=False,
            )
        )
        return issues

    decision = str(gate.get("decision", "")).strip().lower()
    if decision not in ALLOWED_GATE_DECISIONS:
        issues.append(
            ApprovalIssue(
                code="GATE_DECISION",
                message=(
                    f"门禁结论 decision={gate.get('decision')!r}，"
                    f"允许值={sorted(ALLOWED_GATE_DECISIONS)}"
                ),
                blocking=True,
            )
        )

    for check in REQUIRED_GATE_CHECKS:
        value = str(gate.get(check, "")).strip().upper()
        if value and value != "PASS":
            issues.append(
                ApprovalIssue(
                    code=f"GATE_{check.upper()}",
                    message=f"{check}={value}，上生产要求 PASS",
                    blocking=True,
                )
            )

    for check in ADVISORY_GATE_CHECKS:
        value = str(gate.get(check, "")).strip().upper()
        if value and value != "PASS":
            issues.append(
                ApprovalIssue(
                    code=f"GATE_{check.upper()}",
                    message=f"{check}={value}，建议补跑（不阻断）",
                    blocking=False,
                )
            )

    return issues


def enforce_approval(
    strategy_id: str,
    approved_by: str,
    *,
    force: bool = False,
    gate: dict[str, Any] | None = None,
    search_dir: Path | None = None,
) -> list[ApprovalIssue]:
    """执行审批守卫。

    Args:
        strategy_id: 待批准策略 id。
        approved_by: 批准人；空字符串会被硬拦。
        force: 显式越过硬拦（会在日志留下 WARNING 级留痕）。
        gate: 直接给出门禁记录（测试用）；``None`` 时读最新门禁文件。
        search_dir: 门禁文件搜索目录（测试用）。

    Returns:
        全部 issues（含非阻断项，便于上层提示）。

    Raises:
        ApprovalBlockedError: 存在阻断项且 ``force=False``。
    """
    if gate is None:
        gate = latest_gate(strategy_id, search_dir)

    issues = evaluate_approval(strategy_id, approved_by, gate)
    blocking = [issue for issue in issues if issue.blocking]

    if blocking and force:
        logger.warning(
            "⚠️ 审批守卫被 --force 越过：strategy={} | 阻断项={}",
            strategy_id,
            [issue.code for issue in blocking],
        )
    elif blocking:
        raise ApprovalBlockedError(strategy_id, issues)

    for issue in issues:
        if not issue.blocking:
            logger.info("审批提示 [{}] {}", issue.code, issue.message)

    return issues
