#!/usr/bin/env python3
"""Layer dependency auditor — check upward dependencies across QP layers.

手工审计脚本（不属于库代码，不参与 lint/pyright 门禁）。
源自 2026-08-11 宪法审计的 /tmp/audit_layers.py，归档为可复用工具。

用法:
    .venv/bin/python scripts/audit_layers.py [REPO_ROOT]

输出:
    1. 向上依赖违规列表 (target_num > source_num)
    2. 同层/未定层依赖
    3. 层间依赖矩阵 (按文件数)
    4. 数据源 (akshare/tushare) 泄漏检查 (应只在 data 层)

组合根豁免 (ADR-033, 不判违规):
    - qp/pipeline/    — 业务编排组合根 (跨层编排是设计使然)
    - qp/web/         — WebUI 人类接口层 (只读展示)
    - qp/platform/cli/ — CLI 组合根 (ADR-002 唯一入口)
"""

import collections
import os
import re
import sys
from pathlib import Path

ROOT = "/home/shuai/workspace/qt/qp"

# 10 层架构映射 (ADR-029/030 合并后, rule.md 第 3 节)
LAYER_NUM = {
    "platform": 1,
    "data": 2,
    "research": 3,
    "validation": 4,
    "strategy": 5,
    "portfolio": 6,
    "simulation": 7,
    "decision": 8,
    "monitoring": 9,
    "knowledge": 10,
}
EXTRA_DIRS = {"shared", "pipeline", "web", "lineage"}  # 不在 10 层映射中的目录

# 组合根豁免 (ADR-033): 目录 → 说明
COMPOSITION_ROOTS = {
    "pipeline": "业务编排组合根 (ADR-033)",
    "web": "WebUI 人类接口层 (ADR-033)",
}

# CLI 组合根豁免: 文件路径前缀 (ADR-002 唯一入口, ADR-033)
CLI_PREFIX = os.path.join("platform", "cli")

# 正则: import qp.XXX / from qp.XXX import ... （跳过 TYPE_CHECKING 块内的类型引用）
RE_IMP = re.compile(r"^\s*(?:from\s+qp\.([A-Za-z_]\w*)[^\n]*|import\s+qp\.([A-Za-z_]\w*))", re.M)
RE_TYPECHECKING = re.compile(r"if\s+TYPE_CHECKING\s*:.*?^\s*$", re.M | re.S)

# 数据源直接调用: 应只在 data 层（只匹配 import 语句，不匹配字符串标注）
DS = re.compile(
    r"^\s*(?:import\s+ak(?:share)?\b|from\s+akshare\b[^\n]*|from\s+ak\b[^\n]*|import\s+tushare\b[^\n]*|from\s+tushare\b)",
    re.M,
)


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT
    violations: list[tuple] = []  # 向上依赖
    horizontal: list[tuple] = []  # 同层依赖
    unranked: list[tuple] = []  # 涉及未定层目录或 from qp import X

    for layer_dir, s_num in LAYER_NUM.items():
        base = os.path.join(root, layer_dir)
        if not os.path.isdir(base):
            print(f"[WARN] 层目录缺失: {layer_dir}", file=sys.stderr)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root)
                try:
                    src = Path(path).read_text(encoding="utf-8")
                except Exception as e:  # audit tool: report & continue
                    print(f"[WARN] 读取失败 {path}: {e}", file=sys.stderr)
                    continue
                # 剥离 TYPE_CHECKING 块: 类型引用不是运行时依赖
                src_no_tc = RE_TYPECHECKING.sub("", src)
                for m in RE_IMP.finditer(src_no_tc):
                    target = m.group(1) or m.group(2)
                    if not target:
                        continue
                    lineno = src[: m.start()].count("\n") + 1
                    # 跳过同文件内 import (self)
                    if target == layer_dir:
                        continue
                    # CLI 组合根豁免 (ADR-033): 命令处理函数内 lazy import 合法
                    if rel.startswith(CLI_PREFIX):
                        unranked.append((layer_dir, s_num, target, lineno, rel))
                        continue
                    if target in COMPOSITION_ROOTS:
                        # 组合根豁免: 不判违规, 但记录供查看
                        unranked.append((layer_dir, s_num, target, lineno, rel))
                        continue
                    if target not in LAYER_NUM:
                        unranked.append((layer_dir, s_num, target, lineno, rel))
                        continue
                    t_num = LAYER_NUM[target]
                    if t_num > s_num:
                        violations.append((layer_dir, s_num, target, lineno, rel))
                    elif t_num == s_num:
                        horizontal.append((layer_dir, s_num, target, lineno, rel))

    print("=" * 70)
    print("【向上依赖违规 (target 层号 > source 层号)】")
    if not violations:
        print("  ✅ 无向上依赖违规")
    for layer_dir, s_num, target, lineno, rel in violations:
        print(f"  [!] {rel}:{lineno}  {layer_dir}({s_num}) -> {target}({LAYER_NUM[target]})")
    print(f"  共 {len(violations)} 条")

    if unranked:
        print("=" * 70)
        print("【涉及组合根/未定层目录 (ADR-033 豁免, 仅记录)】")
        for layer_dir, _s_num, target, lineno, rel in unranked:
            note = COMPOSITION_ROOTS.get(target, "未定层")
            print(f"  {rel}:{lineno}  {layer_dir} -> {target}  [{note}]")
        print(f"  共 {len(unranked)} 条")

    print("=" * 70)
    print("【层间依赖矩阵 (去重后的文件数)】")
    files_by_edge = collections.Counter()
    for layer_dir, _s_num, target, _lineno, _rel in violations + horizontal + unranked:
        files_by_edge[(layer_dir, target)] += 1
    for (src, tgt), n in sorted(files_by_edge.items()):
        print(f"  {src:12s} -> {tgt:12s}  {n} 文件")

    print("=" * 70)
    print("【附加: 数据源直接调用 (ak. / akshare / tushare) 出现在 data 层之外】")
    found = 0
    for layer_dir in [*list(LAYER_NUM), "pipeline", "web", "lineage"]:
        base = os.path.join(root, layer_dir)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, root)
                src = Path(path).read_text(encoding="utf-8")
                for m in DS.finditer(src):
                    lineno = src[: m.start()].count("\n") + 1
                    if layer_dir != "data":
                        print(f"  [!] {rel}:{lineno}  {m.group(0).strip()}")
                        found += 1
    print(f"  检查完毕, {found} 处泄漏")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
