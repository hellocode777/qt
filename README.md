# QP — Quant Platform

A personal quantitative research & investment decision operating system.

> **Status**: Phase 0-6 Complete — 10-layer architecture fully implemented.  
> **Tests**: 1,800+ test functions | **CLI**: 20+ commands | **Quality**: ruff=0, pyright=0
> **Python**: 3.12 (pinned via `.python-version`)

## Quick Start

```bash
uv sync
uv run qp version
uv run qp doctor
uv run qp --help
```

## Architecture

10-layer enterprise architecture:

| Layer | Name | Status |
|-------|------|--------|
| 1 | `platform/` | ✅ Runtime, config, logging, CLI, scheduler, storage, pipeline |
| 2 | `data/` | ✅ Adapters (Tencent/AKShare/Demo), cleaning, calendar, corporate actions |
| 3 | `research/` | ✅ Features, PurgedKFold, LightGBM, experiments, auto-retrain |
| 4 | `validation/` | ✅ Rule engine, 23 validation rules (factor / overfit / backtest / paper / process / production) |
| 5 | `strategy/` | ✅ SimpleRank, SignalAggregator, StrategyRegistry, PaperTradingTracker |
| 6 | `portfolio/` | ✅ Risk manager, cost model, 4 allocators (equal-weight / Kelly / risk-parity / vol-target), optimizer, risk model |
| 7 | `simulation/` | ✅ SimulatedBroker, slippage models (3), backtest, corporate actions |
| 8 | `decision/` | ✅ TradeRecommendation, DecisionReport, DecisionEngine |
| 9 | `monitoring/` | ✅ KillSwitch, drift, model decay, market regime, alerts (3 channels) |
| 10 | `knowledge/` | ✅ KnowledgeArchive, 5 templates, full-text search |

See `docs/` for architecture decisions, design plans, and credibility audit.

## Key Commands

```bash
qp run daily              # End-to-end pipeline
qp validate               # Validation gate
qp portfolio report       # Portfolio KPI dashboard
qp decide [strategy]      # Trade recommendations (bilingual)
qp backtest run           # Broker-based backtest
qp monitor check          # Daily safety checks
qp paper start [strategy] # 30-day paper trading
qp retrain [strategy]     # Monthly model retrain
```

## Development

```bash
uv run ruff format        # Auto-format
uv run ruff check         # Lint (0 errors)
uv run pyright            # Type-check (0 errors)
uv run pytest             # Run tests (1049 passed)
```

## Design Decisions

- **Decision-support system**, not automated trading — system produces recommendations, user manually executes
- Hybrid architecture: DataFrame pipelines for research + Domain Model for portfolio/decision
- Everything is a Pipeline (`BasePipeline.run(context) -> PipelineResult`)
- Data Products isolate consumers from raw data sources (ADR-013)
- Purged KFold mandatory for all models (ADR-021)
- No `print()` — always use Logger | No bare `except:` | No `utils/` directory

## License

MIT
