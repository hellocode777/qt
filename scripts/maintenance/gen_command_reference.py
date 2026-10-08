#!/usr/bin/env python
"""Generate ``docs/command_reference.md`` — the full QP CLI command reference.

The CLI definition in ``qp/platform/cli/parser.py`` is the single source of
truth, so this doc is *generated*, never hand-edited:

    .venv/bin/python scripts/maintenance/gen_command_reference.py

Use ``--check`` to verify the committed doc matches the CLI (exit 1 + message when
stale); ``tests/unit/test_docs_command_reference.py`` runs exactly that, so changing
the CLI without regenerating fails the suite instead of silently rotting the doc.
``--out PATH`` renders to another file (used by the determinism test).

The render must stay **deterministic**: ``--check`` is a byte comparison, so the
document must not embed anything that changes on its own (build date/time, host,
PID) — otherwise the guard goes red the next day without any CLI change.

Two kinds of commands exist:

* **declared** — Click owns the parameters (``--foo`` shows up on the command
  object); options, defaults and help text are read straight off the object.
* **pass-through** — ``ignore_unknown_options`` commands that read ``sys.argv``
  inside the handler (e.g. ``qp run``, ``qp experiment run``); their flags are
  scanned out of the handler source and marked as such.

Command → handler mapping is parsed from ``parser.py`` with ``ast`` (the lazy
``from qp.platform.cli.commands.<mod> import cmd_<x>`` inside each wrapper),
following decorator parents so nested groups (``qp strategy approved``) and
``sys.argv[2]`` sub-dispatches (``qp pipeline list``) are covered too — the
"代码入口" column cannot drift from the code.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import re
import sys
from pathlib import Path

import click

OUT = Path("docs/command_reference.md")
PARSER = Path("qp/platform/cli/parser.py")
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")
SKIP_FLAGS = {"--help", "--version"}

# Hand-maintained, but checked at generation time: every command cited here must
# exist in the live Click tree (or the pre-existing command/flag used below).
PRE_EXISTING = {
    "qp ingest 2015-01-01": "date argument",
    "qp position show <position_id>": "position_id",
    "qp position history 20": "limit",
    "qp proposal show <proposal_id>": "proposal_id",
    "qp proposal approve <proposal_id>": "proposal_id",
    "qp strategy approve <strategy_id> --by <名字>": "strategy_id + --by",
    "qp retrain <strategy_id> --dry-run": "--dry-run flag",
    "qp experiment show <experiment_id>": "experiment_id",
    "qp experiment validate <experiment_id>": "experiment_id",
    "qp factor compute --date 2026-09-24": "--date flag",
    "qp paper start <strategy_id>": "strategy_id",
    "qp model show <model_id>": "model_id",
}

WORKFLOWS: list[tuple[str, str, list[str]]] = [
    (
        "每日完整链路（调度器工作日 18:00 自动跑；人工补跑用这条）",
        "抓数据 → 因子计算 → 因子健康 → regime → 策略信号 → 风控 → 决策包 → 影子盘",
        ["qp run daily", "qp run daily --skip-fetch", "qp run daily --skip-factor-calc"],
    ),
    (
        "数据准备",
        "行情 / 基准指数 / 基本面 / 资金流",
        [
            "qp data fetch",
            "qp data index",
            "qp fundamental",
            "qp fundamental --quick",
            "qp capital-flow --quick",
            "qp ingest 2015-01-01",
        ],
    ),
    (
        "因子研究与健康",
        "算因子 → 看因子目录 → 全历史健康重算 → 查健康/生命周期 → 出报告",
        [
            "qp factor compute",
            "qp factor compute --date 2026-09-24",
            "qp factor catalog",
            "qp factor update-health",
            "qp factor health",
            "qp factor list",
            "qp factor report",
        ],
    ),
    (
        "策略回测实验",
        "多因子实验（--skip-gate 跳过门禁）→ 列表 / 详情 / 对比 / 单实验验证",
        [
            "qp experiment run multifactor --strategy momentum_vol_full --start 2025-09-05 --end 2026-08-31 --top-n 10 --rebalance 20",
            "qp experiment list",
            "qp experiment show <experiment_id>",
            "qp experiment compare",
            "qp experiment validate <experiment_id>",
        ],
    ),
    (
        "策略生命周期（研究 → 生产）",
        "列策略 → 跑验证门禁 → 审批冻结快照 → 生成决策包 → 人工确认提案",
        [
            "qp strategy list",
            "qp strategy approved list",
            "qp validate",
            "qp strategy approve <strategy_id> --by <名字>",
            "qp decide",
            "qp decide --force",
            "qp decide --review",
            "qp proposal list",
            "qp proposal show <proposal_id>",
            "qp proposal approve <proposal_id>",
            "qp strategy deactivate <strategy_id>",
        ],
    ),
    (
        "持仓与组合",
        "持仓明细/盈亏 → 组合报告与风险",
        [
            "qp position list",
            "qp position show <position_id>",
            "qp position pnl",
            "qp position history 20",
            "qp portfolio report",
            "qp portfolio risk",
        ],
    ),
    (
        "监控与告警",
        "系统检查 → 市场 regime → 告警通道自测",
        ["qp monitor check", "qp monitor regime", "qp monitor alert-test"],
    ),
    (
        "模拟盘 / 影子盘",
        "按决策包假钱建仓并逐日 mark-to-market；paper 是 30 天策略验证",
        ["qp simulation shadow", "qp paper start <strategy_id>", "qp paper status"],
    ),
    (
        "模型与血缘",
        "模型列表/详情、重训触发、血缘快照",
        [
            "qp model list",
            "qp model show <model_id>",
            "qp retrain",
            "qp retrain <strategy_id> --dry-run",
            "qp lineage snapshot",
        ],
    ),
    (
        "运维",
        "环境自检、调度器（systemd 管理）、Web UI",
        ["qp doctor", "qp version", "qp scheduler", "qp web start"],
    ),
]


def _one_line(text: str) -> str:
    return (text or "").strip().split("\n")[0].replace("|", "/")


def _decl_map() -> tuple[dict[tuple[str, ...], tuple[str, str]], dict[tuple[str, ...], list[str]]]:
    """(command path → (module, function)) + manually dispatched subcommands."""
    src = PARSER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    decls: dict[str, dict[str, object]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        info: dict[str, object] = {
            "kind": None,
            "parent": None,
            "name": node.name,
            "imports": None,
            "dispatch": [],
        }
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            attr = dec.func.attr
            owner = dec.func.value.id if isinstance(dec.func.value, ast.Name) else None
            if owner == "click":  # @click.group() / @click.command() on the root
                continue
            if attr not in ("group", "command"):
                continue
            info["kind"] = attr
            info["parent"] = None if owner in (None, "cli") else owner
            if attr == "command" and dec.args and isinstance(dec.args[0], ast.Constant):
                value = dec.args[0].value
                if isinstance(value, str):
                    info["name"] = value
            elif attr == "command":
                info["name"] = node.name.replace("_", "-")
        if info["kind"] is None:
            continue
        imported = next(
            (s for s in ast.walk(node) if isinstance(s, ast.ImportFrom) and s.module),
            None,
        )
        if imported is not None and imported.names:
            info["imports"] = (str(imported.module), imported.names[0].name)
        node_src = ast.get_source_segment(src, node) or ""
        info["dispatch"] = re.findall(r'argv\[\s*2\s*\]\s*==\s*"([^"]+)"', node_src)
        decls[node.name] = info

    def path_of(fname: str) -> tuple[str, ...]:
        info = decls[fname]
        parent = info["parent"]
        if isinstance(parent, str) and parent in decls:
            return (*path_of(parent), str(info["name"]))
        return (str(info["name"]),)

    handlers: dict[tuple[str, ...], tuple[str, str]] = {}
    dispatch: dict[tuple[str, ...], list[str]] = {}
    for fname, info in decls.items():
        path = path_of(fname)
        imports = info["imports"]
        if isinstance(imports, tuple):
            handlers[path] = imports
        subs = info["dispatch"]
        if isinstance(subs, list) and subs:
            dispatch[path] = [str(s) for s in subs]
    return handlers, dispatch


def _collect(cli: click.Group) -> list[tuple[tuple[str, ...], click.Command]]:
    """Pre-order flat list of (path, command) at any nesting depth."""
    flat: list[tuple[tuple[str, ...], click.Command]] = []

    def walk(group: click.Group, prefix: tuple[str, ...]) -> None:
        for name, cmd in sorted(group.commands.items()):
            path = (*prefix, name)
            flat.append((path, cmd))
            if isinstance(cmd, click.Group):
                walk(cmd, path)

    walk(cli, ())
    return flat


def _pass_through_flags(module: str, func: str) -> list[tuple[str, str]]:
    """[(flag, description)] scanned from the handler source.

    Pass-through handlers come in two shapes: ``arg == "--flag"`` comparisons
    (``qp capital-flow``) and a ``print()`` usage block (``qp experiment run``).
    Both are plain literals in the handler, so scan every ``--flag`` literal and
    attach the best description we can find (usage text, else comment block).
    """
    try:
        mod = __import__(module, fromlist=["_"])
        target = getattr(mod, func, None)
        if target is None:
            return []
        src = inspect.getsource(target)
    except Exception:
        return []

    order: list[str] = []
    desc: dict[str, str] = {}
    lines = src.splitlines()

    def comment_block(idx: int) -> str:
        block: list[str] = []
        j = idx
        while j >= 0 and lines[j].strip().startswith("#"):
            block.append(lines[j].strip().lstrip("# ").strip())
            j -= 1
        return re.sub(r"\s{2,}", " ", " ".join(reversed(block))).strip()

    for i, line in enumerate(lines):
        if '"' not in line and "'" not in line:
            continue
        for flag in sorted(set(FLAG_RE.findall(line)), key=line.index):
            if flag in SKIP_FLAGS:
                continue
            if flag not in desc:
                desc[flag] = ""
                order.append(flag)
            if desc[flag]:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                desc[flag] = comment_block(i)
            elif stripped[:1] in ("'", '"') or "print(" in line:
                for literal in re.findall(r'"([^"]*)"', line) + re.findall(r"'([^']*)'", line):
                    if flag in literal and len(literal.strip()) > len(flag) + 2:
                        text = re.sub(r"\s{2,}", " ", literal.replace(flag, "")).strip(" -:")
                        if len(text) > 3:
                            desc[flag] = text
                            break
            else:
                text = comment_block(i - 1)
                if not text and i + 1 < len(lines) and lines[i + 1].strip().startswith("#"):
                    text = lines[i + 1].strip().lstrip("# ").strip()
                desc[flag] = text
    return [(f, desc[f]) for f in order]


def _param_rows(cmd: click.Command) -> list[list[str]]:
    rows: list[list[str]] = []
    for p in cmd.params:
        if isinstance(p, click.Argument):
            rows.append([p.name, "位置参数", "必填" if p.required else "可选", str(p.type), ""])
            continue
        if "--help" in getattr(p, "opts", []):
            continue
        flags = " ".join(getattr(p, "opts", []) or [])
        default = "" if p.default is None else str(p.default)
        if isinstance(p, click.Option) and p.is_flag:
            default = f"{default}（开关）"
        rows.append(
            [
                flags,
                "选项",
                "必填" if p.required else "可选",
                default,
                (getattr(p, "help", "") or "").strip(),
            ]
        )
    return rows


def _section(path, cmd, flat, handlers, dispatch) -> list[str]:
    title = "qp " + " ".join(path)
    level = len(path) + 2
    out = [f"\n{'#' * level} `{title}`\n", f"**作用**：{_one_line(cmd.help or '')}\n"]

    if isinstance(cmd, click.Group):
        children = ["qp " + " ".join(p) for p, _ in flat if p[:-1] == path]
        out.append("**子命令**：" + "、".join(f"`{c}`" for c in children) + "\n")
        entry = handlers.get(path)
        if entry:
            out.append(f"\n**代码入口**：`{entry[0]}.{entry[1]}`\n")
        return out

    subs = dispatch.get(path)
    if subs:
        out.append(
            "**手动分派子命令**（wrapper 里按 `sys.argv[2]` 分派，不是 Click 子命令）："
            + "、".join(f"`{title} {s}`" for s in subs)
            + "\n"
        )
    rows = _param_rows(cmd)
    if rows:
        out.append("| 参数 | 类型 | 必填 | 默认 | 说明 |")
        out.append("|---|---|---|---|---|")
        for r in rows:
            out.append("| `{}` | {} | {} | `{}` | {} |".format(*[c.replace("|", "/") for c in r]))
    else:
        entry = handlers.get(path)
        flags = _pass_through_flags(*entry) if entry else []
        if flags:
            out.append("**透传参数**（handler 直接读 `sys.argv`，Click 不知情）：\n")
            out.append("| flag | 说明（原文摘录） |")
            out.append("|---|---|")
            for flag, comment in flags:
                out.append(f"| `{flag}` | {comment or '—'} |")
        else:
            out.append("_无参数（或由 handler 自行解析，见代码入口）。_\n")
    entry = handlers.get(path)
    out.append(
        f"\n**代码入口**：`{entry[0]}.{entry[1]}`\n"
        if entry
        else "\n**代码入口**：`qp/platform/cli/parser.py`\n"
    )
    return out


def _known_commands(flat, dispatch) -> set[str]:
    known = {"qp " + " ".join(p) for p, c in flat if not isinstance(c, click.Group)}
    known |= {"qp " + " ".join((*path, s)) for path, subs in dispatch.items() for s in subs}
    return known


def _parse_argv(argv: list[str]) -> tuple[bool, Path]:
    """``--check`` compares instead of writing; ``--out PATH`` retargets the file."""
    out = OUT
    if "--out" in argv:
        index = argv.index("--out")
        if index + 1 >= len(argv):
            raise SystemExit("--out 需要一个路径参数")
        out = Path(argv[index + 1])
    return "--check" in argv, out


def _click_version() -> str:
    try:
        from importlib.metadata import version

        return version("click")
    except Exception:  # pragma: no cover — click is a hard dependency
        return "unknown"


def _report_stale(out_path: Path, current: str, rendered: str) -> None:
    """Diagnose a --check mismatch: counts, env fingerprint, bounded unified diff.

    The counts alone ("条目 60 → 60") say nothing when the tree did not change —
    this happened for real once (a volatile build date in the header), so always
    surface the concrete lines that differ plus the interpreter that rendered them.
    """
    n_doc = len(re.findall(r"^\| `qp ", current, re.M))
    n_new = len(re.findall(r"^\| `qp ", rendered, re.M))
    diff_lines = list(
        difflib.unified_diff(
            current.splitlines(),
            rendered.splitlines(),
            fromfile=str(out_path),
            tofile="re-rendered-from-CLI",
            lineterm="",
            n=1,
        )
    )
    report = [
        f"STALE: {out_path} 与当前 CLI 不一致（速查表条目 {n_doc} → {n_new}）。"
        "重跑 `python scripts/maintenance/gen_command_reference.py` 重新生成。",
        f"env: python={sys.version.split()[0]} click={_click_version()} cwd={Path.cwd()}",
    ]
    report.extend(diff_lines[:40])
    if len(diff_lines) > 40:
        report.append(f"... diff 共 {len(diff_lines)} 行，仅显示前 40 行")
    print("\n".join(report), file=sys.stderr)


def main() -> int:
    from qp.platform.cli.parser import cli

    check, out_path = _parse_argv(sys.argv[1:])
    handlers, dispatch = _decl_map()
    flat = _collect(cli)
    leaves = [(p, c) for p, c in flat if not isinstance(c, click.Group)]
    groups = [(p, c) for p, c in flat if isinstance(c, click.Group)]
    nested = [p for p, _ in groups if len(p) > 1]
    dispatched = sum(len(v) for v in dispatch.values())

    out: list[str] = [
        "# QP CLI 命令手册（全量）\n",
        "> **本文件由脚本生成，请勿手改**："
        "`.venv/bin/python scripts/maintenance/gen_command_reference.py`\n"
        # NOTE: never render a volatile field (build date/time, host, PID) here.
        # `--check` compares bytes, so any such field makes the guard fail on the
        # *next* day/runner even when the CLI did not change.
        "> 权威来源：`qp/platform/cli/parser.py`（Click 定义）；"
        f"可执行命令 **{len(leaves) + dispatched}** 条"
        f"（Click 命令 {len(leaves)} + 手动分派 {dispatched}），命令节点 {len(flat)} 个"
        f"（命令组 {len(groups)} 个，含嵌套组 {len(nested)} 个）。\n"
        "> CLI 入口：`.venv/bin/qp`（等价 `python -m qp.platform.cli.main`；**勿用 `uv run qp`**，Python 3.12 下载会超时）。\n"
        "> 相关：`docs/ai/COMMAND_MAP.md`（AI 定位：命令 → 代码入口 → 流程）、`docs/user_guide.md`（使用指南）。\n",
        "\n## 0. 读法与约定\n",
        "- 每条命令给出：**作用**、**参数表**、**代码入口**。\n"
        "- 标 **透传参数** 的命令由 handler 直接读 `sys.argv`：Click 层不知道它支持哪些 flag，"
        "因此 `qp <cmd> --help` 只打印一行简介；下表来自 handler 源码扫描，"
        "说明列是**源码注释/用法文本的原文摘录**（可能不完整），语义以源码为准。\n"
        "- 退出码：`0` = 成功，非 0 = 失败（`qp run` / `qp validate` 等会把 pipeline 状态映射成退出码）。\n"
        "- 触及生产的命令（`run`、`retrain`、`proposal approve`、`strategy approve` 等）先读 `docs/constitution/rule.md`。\n"
        "- `<xxx_id>` 是占位符，不是字面量；执行前用对应的 `list` 命令拿真实 ID。\n",
        "\n## 1. 速查表（全部可执行命令）\n",
        "| 命令 | 作用 |",
        "|---|---|",
    ]
    out += [f"| `qp {' '.join(p)}` | {_one_line(c.help or '')} |" for p, c in leaves]
    for path, subs in sorted(dispatch.items()):
        for s in subs:
            out.append(
                f"| `qp {' '.join((*path, s))}` | "
                f"手动分派子命令（`qp {' '.join(path)}` 内按 `sys.argv[2]` 分派） |"
            )

    out.append("\n## 2. 顶层命令与命令组\n")
    out.append("> 命令组只列子命令；参数细节在其子命令小节里。\n")
    for path, cmd in flat:
        out += _section(path, cmd, flat, handlers, dispatch)

    out.append("\n## 3. 典型工作流（示例）\n")
    out.append("> 示例只做形状说明：`<xxx_id>` 换成真实 ID；flag 见对应命令的参数表。\n")
    known = _known_commands(flat, dispatch)
    extra = set(PRE_EXISTING) - known  # flags/args are documented below the command
    for title, desc, cmds in WORKFLOWS:
        out.append(f"\n**{title}** — {desc}\n")
        out.append("```bash")
        out.extend(cmds)
        out.append("```")
        for line in cmds:
            tokens = line.split()
            head = next(
                (" ".join(tokens[:n]) for n in (4, 3, 2) if " ".join(tokens[:n]) in known),
                None,
            )
            if head is None:
                raise SystemExit(
                    f"workflow cites unknown command: {line} (extra seen: {sorted(extra)[:3]})"
                )

    out.append("\n## 4. 维护\n")
    out.append(
        "- 命令增删改后重跑生成器即可（`parser.py` 才是权威；本文件不建议手改）。\n"
        "- **忘了重跑不会静默腐化**：`tests/unit/test_docs_command_reference.py` 会跑 "
        "`gen_command_reference.py --check`，文档与 CLI 不一致即测试失败。\n"
        "- 生成器不联网、不写数据，只读 `parser.py` 与 handler 源码；两次运行结果字节一致"
        "（**刻意不写生成日期**：`--check` 是字节比对，任何随时间变化的字段都会让守卫在"
        "第二天必然失败）。文档新鲜度看 `git log -1 -- docs/command_reference.md`。\n"
        "- 想补充示例，改生成器顶部的 `WORKFLOWS`（带存在性断言，写错命令会直接报错退出）。\n"
    )

    rendered = "\n".join(out) + "\n"
    n_bytes = len(rendered.encode("utf-8"))
    if check:
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if current != rendered:
            _report_stale(out_path, current, rendered)
            return 1
        print(f"up to date: {out_path} ({n_bytes} bytes)")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    dispatched = sum(len(v) for v in dispatch.values())
    print(
        f"wrote {out_path} ({n_bytes} bytes) | commands={len(leaves)} "
        f"+dispatched={dispatched} | groups={len(groups)} (nested {len(nested)}) | nodes={len(flat)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
