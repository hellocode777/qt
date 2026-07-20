# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

QP (Quant Platform) is a quantitative investment research and trading platform with a strict 12-layer architecture. The project is currently in **Sprint 0 (Bootstrap)** — the directory skeleton and design documentation are in place, but all source files are empty placeholders awaiting implementation.

## Build & Quality Commands

The project uses `uv` for package management. No `pyproject.toml` exists yet — creating one is Milestone 0.

```bash
uv sync          # Install dependencies (once pyproject.toml exists)
uv run qp version  # Verify the CLI works
ruff format      # Auto-format code
ruff check       # Lint (zero errors required)
pyright          # Type-check (zero errors required)
pytest           # Run all tests
pytest tests/unit/path/to/test_file.py  # Run a single test file
```

Definition of Done for every milestone:
- `uv sync` succeeds
- `ruff format` passes
- `ruff check` zero errors
- `pyright` zero errors
- `pytest` all pass
- At least one CLI command is runnable
- README is updated
- New ADR added if design changed

## Architecture: Twelve Layers

The system is organized into 12 layers with strict boundaries. **No layer may import or depend on a layer above it.** Cross-layer shortcuts are forbidden.

```
Layer 1:  platform/      — Runtime foundation (config, logging, scheduler, storage, CLI, pipeline engine)
Layer 2:  data/          — Trusted, versioned Data Products (never expose raw data sources)
Layer 3:  research/      — Reproducible experiments: features, labels, models, purged CV
Layer 4:  validation/    — Gate between research and strategy; rule-engine-based
Layer 5:  strategy/      — Investment policy; outputs Decisions, not Orders
Layer 6:  portfolio/     — Portfolio construction, risk control, capital allocation
Layer 7:  simulation/    — Paper trading, shadow trading, backtest
Layer 8:  decision/      — Explainable, auditable decisions (not AI/LLM)
Layer 9:  monitoring/    — Observe only, never decide; drift detection, kill switch
Layer 10: knowledge/     — Long-term memory: post-mortems, experiment summaries, failure analysis
```

**Key boundary**: `data/` produces Data Products — consumers (research, strategy, etc.) never know which data source (AkShare, Tushare) provided the raw data. `research/` must never call `ak.stock_zh_a_hist(...)` directly.

## Platform Layer (`qp/platform/`) — Current Bootstrap Focus

Platform is the kernel that owns all infrastructure. Every other layer runs on top of it.

| Subsystem | Purpose |
|---|---|
| `runtime/` | Application lifecycle, state machine (CREATED → INITIALIZING → READY → RUNNING → STOPPING → TERMINATED), composition root |
| `config/` | 4-tier priority: CLI args > env vars > config.toml > defaults. Frozen after startup. |
| `logging/` | Unified logging via Loguru, no `print()` allowed |
| `scheduler/` | systemd timer → CLI → APScheduler → Job Registry. No Airflow/Celery. |
| `storage/` | StorageFactory provides DuckDB, SQLite, Parquet backends. Does NOT provide business Repositories. |
| `pipeline/` | `BasePipeline.run(context) -> PipelineResult` — all long-running work is a Pipeline |
| `cli/` | Single entry point `qp` — all operations go through it |
| `metadata/` | Version, environment, runtime metadata |

## Shared Module Constraints (`qp/shared/`)

Only four things are allowed — no `utils/`, `helpers/`, or `common/`:

```
shared/
├── protocols/   # Abstract interfaces (BaseStrategy, BaseModel, etc.)
├── types/       # Enums and type definitions
├── constants/   # DEFAULT_TIMEZONE, etc.
└── exceptions/  # Custom exception classes
```

## Key Design Decisions (from ADRs)

- **ADR-001**: Hybrid architecture — DataFrame pipelines for data/research, Domain Model (Repository + strong types) for portfolio/order/decision
- **ADR-003**: No DI framework — explicit composition root in `builder.py`
- **ADR-005**: No event bus in Phase 0 — direct calls between layers
- **ADR-006**: Everything is a Pipeline, not a script
- **ADR-012**: Runtime owns everything — pipelines access `runtime.logger`, never create their own
- **ADR-013**: Data Product Architecture — consumers depend on Dataset, never on data sources
- **ADR-021**: Purged KFold is mandatory for all models (no plain KFold)
- **ADR-022**: Notebooks are exploration-only, never production
- **ADR-029**: Risk and Capital Allocation are merged into `portfolio/` in code (not separate layers)

## Tech Stack (from TDRs)

| Technology | Purpose |
|---|---|
| DuckDB | Analytical database |
| Parquet | Columnar storage format |
| LightGBM | Default ML model |
| Pydantic | Configuration and data models |
| Loguru | Logging |
| APScheduler | Job scheduling |
| Polars | DataFrame library (alternative to Pandas) |
| AkShare | Current data source |

## Terminology (Ubiquitous Language)

Everywhere — docs, code, docstrings, comments — use these exact terms:

- **Pipeline** (never Workflow, Flow, Process, Task Chain)
- **Job** = a schedule plan; **Task** = one action in a job; **Run** = one pipeline execution instance
- **Signal ≠ Prediction**: Prediction is raw model output; Signal is tradeable
- **Order ≠ Trade**: Order may be rejected; Trade is confirmed execution
- **Experiment ≠ Run**: Experiment is the container, Run is one execution
- **Dataset** = trusted data product; **Data Source** = raw provider (AkShare, etc.)

## Naming Conventions

| Type | Convention | Example |
|---|---|---|
| Files | `snake_case.py` | `feature_pipeline.py` |
| Classes | `PascalCase` | `FeaturePipeline` |
| Functions | `snake_case` | `build_feature()` |
| Constants | `UPPER_CASE` | `DEFAULT_TIMEZONE` |
| Abstract classes | `BaseXXXX` | `BaseStorage`, `BaseBroker` |

## Hard Rules

- CLI name is `qp` — no second entry point will be created
- `main` branch must always be installable, bootable, runnable, testable
- No `print()` — always use Logger
- No bare `except:` — always specify exception types
- No circular imports
- No `utils/`, `helpers/`, `misc/`, `scripts/`, `common_utils/` directories — every module must belong to a layer
- Raw data is immutable — never modified, only appended
- Configuration is frozen after runtime startup
- Secrets (API keys) come from environment variables only, never in config files
