# DP-002: Factor Pipeline

| 属性 | 值 |
|------|-----|
| 状态 | Proposed |
| 版本 | v1.0 |
| 所属层 | Layer 3 — Research Layer |
| 依赖 | DP-001 Data Layer |
| 被依赖 | DP-003 Strategy Engine, DP-008 Monitoring |

---

## 1. Overview

The Factor Pipeline transforms raw market and fundamental data into standardized, validated, and reusable factor signals. It acts as the bridge between the Data Layer and the Research / Strategy Layer.

### 1.1 Position in the Overall Architecture

```
Platform Layer
      │
      ▼
Data Layer
      │
      ▼
Research Layer
      │
      ├───────────────┐
      │               │
      ▼               │
 Factor Pipeline      │   ← This document
      │               │
      ▼               │
 Strategy Engine      │
      ▼               │
 Portfolio Risk       │
      ▼               │
 Capital Allocation   │
      ▼               │
 Simulation Layer     │
      ▼               │
 Decision Layer       │
      ▼               │
 Monitoring Layer     │
      ▼               │
 Knowledge Layer      │
```

### 1.2 Pipeline Overview

```
                   Raw Dataset
                         │
                         ▼
              Factor Compute Engine
                         │
                         ▼
               Factor Refinery Engine
                         │
                         ▼
                  Factor Store
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
     Factor Health Engine      Feature Matrix Builder
             │                       │
             └───────────┬───────────┘
                         ▼
                 Strategy / Model
```

---

## 2. Design Goals

### 2.1 Decoupling
Each factor is completely independent. A new factor can be added without modifying existing factors, the strategy engine, the model layer, or the portfolio layer. Only registration is required.

### 2.2 Reproducibility
Every factor output must be reproducible. Given the same raw dataset, same factor version, and same parameters, the pipeline must generate identical results.

### 2.3 Reusability
Factors are reusable research assets. A factor is never tied to a specific strategy. It only produces standardized numerical scores. Strategies decide how those scores are used.

### 2.4 Observability
Every factor is continuously monitored. The system must always know:
- Whether a factor is healthy
- Whether its predictive power is degrading
- Whether it should be disabled

### 2.5 Scalability
The architecture should support tens of factors today, hundreds of factors tomorrow, without architectural changes.

---

## 3. Pipeline Architecture

### 3.1 Component Diagram

```
Raw Data
    │
    ▼
Factor Compute       ← Raw factor calculation only, no processing
    │
    ▼
Factor Refinery      ← Winsorize → Neutralize → Normalize
    │
    ▼
Factor Store         ← Persist raw + refined + feature matrices
    │
    ├──► Factor Health Engine   ← Continuous IC / ICIR / coverage / drift monitoring
    │
    └──► Feature Matrix Builder ← ML-ready feature matrix for models
              │
              ▼
         Model / Combine
              │
              ▼
         Portfolio Construction
              │
              ▼
         Risk Control
              │
              ▼
         Decision Package
```

### 3.2 Key Principle: Factor vs Signal vs Decision

```
Factor          →  score (e.g. -2.31, +1.22, 0.03)
    │               Never: Buy/Sell/Hold
    │               Always: standardized numerical value
    ▼
Strategy        →  signal (e.g. overweight, underweight)
    │               Decides how to use the score
    ▼
Portfolio       →  position (e.g. +5%, -2%)
    │               Converts signal to weight
    ▼
Decision        →  order (e.g. BUY 1000 shares)
                    Converts weight to executable order
```

A factor that outputs `Buy=True` is architecturally wrong — it loses reusability across strategies.

---

## 4. Component Design

### 4.1 Factor Compute Engine

**Responsibility**: Generate raw factor values. No normalization, no weighting, no ranking, no strategy logic.

| Aspect | Detail |
|--------|--------|
| Input | Market Data, Fundamental Data, Industry Classification, Trading Calendar |
| Output | Raw Factor Matrix: `Date × Symbol × FactorValue` |
| Rules | No normalization. No weighting. No ranking. No strategy logic. Only compute. |

**Example Output**:
```
2026-08-05
          Momentum_3M
600000      1.35
600519      0.72
000001     -0.81
```

**Current Implementation**: `qp/research/feature/compute.py` — `compute_all_factors()` with 18 price/volume factors across momentum, volatility, volume, and money flow categories. Quality factors in `qp/research/feature/quality.py`.

### 4.2 Factor Refinery Engine

**Responsibility**: Transform raw factors into standardized research features.

**Processing Pipeline**:
```
Raw Factor Values
    │
    ▼
Fill Missing Values      ← Cross-sectional median or forward-fill
    │
    ▼
MAD Winsorization        ← Clip outliers at median ± 5×MAD
    │
    ▼
Industry Neutralization  ← Subtract industry median or OLS residual
    │
    ▼
Market Cap Neutralization ← Strip size bias (OLS)
    │
    ▼
Z-score Standardization  ← Mean 0, std 1 per cross-section
    │
    ▼
Clean Factor Matrix
```

**Current Implementation**: `qp/research/factor_processor.py` — `factor_pipeline()` orchestrates winsorize → normalize → neutralize → orthogonalize → combine.

### 4.3 Factor Store

**Responsibility**: Persist every processed factor for future reuse. Store only data — no evaluation metrics.

**Directory Structure**:
```
factor_store/
├── raw/                    ← Raw factor values (before any processing)
│   ├── Momentum_3M/
│   ├── Volatility_20D/
│   └── ...
├── refined/                ← After refinery (winsorized, neutralized, normalized)
│   ├── Momentum_3M/
│   └── ...
└── feature/                ← Final feature matrix for ML consumption
    └── feature_matrix.parquet
```

**Required Metadata per stored dataset**:
```
factor_name, version, date_range, dataset_version, created_at, row_count, hash
```

**Why three versions?** If a downstream result is wrong, you can trace back layer by layer:
```
Feature → Refined → Raw → Root Cause
```
Without recomputing the entire pipeline.

### 4.4 Factor Health Engine

**Responsibility**: Continuously evaluate factor quality. This is a separate concern from storage.

**Monitored Metrics**:

| Metric | 30d | 90d | 252d | Threshold |
|--------|:---:|:---:|:----:|-----------|
| IC (Rank) | ✅ | ✅ | ✅ | \|IC\| ≥ 0.02 |
| IC IR | ✅ | ✅ | ✅ | ≥ 0.30 |
| Coverage | ✅ | — | — | ≥ 95% |
| Missing Rate | ✅ | — | — | ≤ 5% |
| Turnover | ✅ | — | — | Within limit |
| Monotonicity | ✅ | — | — | Q5-Q1 spread t-stat ≥ 2.0 |
| IC Decay Rate | ✅ | — | — | Linear slope > -0.0005/day |
| Correlation Drift | ✅ | — | — | PSI < 0.25 |

**Health Status Classification**:

| Status | Condition | Action |
|--------|-----------|--------|
| HEALTHY | All metrics within threshold | OK |
| WARNING | 1-2 metrics degrading, \|IC_30d\| > 50% of reference | Monitor, prepare weight reduction |
| DEGRADED | \|IC_30d\| < 30% of reference, or PSI ≥ 0.25 | Reduce weight 50% |
| STALE | \|IC_30d\| < 0.01 | Remove from ensemble |

**Output**: `factor_health.parquet` — one row per factor per day.

**Example Health Record**:
```
Momentum_3M
──────────────
IC30        0.061
IC250       0.073
ICIR        0.82
Coverage    99.8%
Decay       Normal
Status      Healthy
```

**Current Implementation**: `qp/monitoring/factor_health.py` — `FactorHealthMonitor` class with HEALTHY/WARNING/DEGRADED/STALE classification. `FactorHealthLogger` persists to Parquet. `FactorHealthPipeline` integrates with daily monitoring.

### 4.5 Validation Gate

**Responsibility**: Before a factor becomes available for research or production, it must pass predefined quality rules.

**Gate Rules**:

| Rule | Threshold | Severity |
|------|-----------|:--------:|
| Coverage | > 95% | Hard fail |
| \|IC\| | > 0.02 | Hard fail |
| IC IR | > 0.30 | Hard fail |
| IC t-stat | > 2.0 | Hard fail |
| Monotonicity | Q5-Q1 spread t-stat ≥ 2.0 | Hard fail |
| Missing Rate | < 5% | Hard fail |
| Max Correlation | < 0.85 (with any existing factor) | Warning |
| Turnover | Within 2× benchmark turnover | Warning |
| Min Sample Period | ≥ 3 years | Hard fail |

**Gate Decisions**:
```
PASS     → Register, make available for research
WARNING  → Available but flagged, needs monitoring
FAILED   → Archive to Research Debt, not available
```

**Current Implementation**: `qp/validation/checks/factor_checks.py` — `RankICCheck`, `ICIRCheck`, `TStatCheck`, `StratificationCheck`, `NeutralizationCheck`, `MinSamplePeriodCheck`. `qp/validation/engine.py` — `RuleEngine` with registry-based rule composition.

### 4.6 Feature Matrix Builder

**Responsibility**: Construct the final ML-ready feature matrix from all validated factors.

**Input**: All PASS-status factors from the Factor Store.

**Output**:
```
Date         Symbol    Factor1   Factor2   Factor3   ...   Future_Return
2026-08-05   600000    1.35      0.72      -0.81     ...   0.023
2026-08-05   600519    0.72      -1.10     0.55      ...   -0.015
```

This dataset is consumed by Linear Models, LightGBM, XGBoost, CatBoost, and Deep Learning models.

---

## 5. Factor Lifecycle

```
Research              ← Idea exploration, hypothesis formation
    │
    ▼
Implementation        ← Code the factor class, register metadata
    │
    ▼
Computation           ← Run compute() on historical data
    │
    ▼
Refinement            ← Winsorize → Neutralize → Normalize
    │
    ▼
Storage               ← Persist to Factor Store (raw + refined)
    │
    ▼
Health Evaluation     ← Compute IC / ICIR / coverage / turnover
    │
    ▼
Validation Gate       ← PASS / WARNING / FAILED
    │
    ▼
Registry              ← Record factor metadata, version, status
    │
    ▼
Available             ← Factor is now usable by strategies/models
    │
    ▼
Model Training        ← Use factor in feature matrix
    │
    ▼
Strategy              ← Strategy consumes factor score
    │
    ▼
Monitoring            ← Continuous health tracking
    │
    ▼
Retirement            ← IC decays below threshold → deprecate
```

---

## 6. Factor Standard

Every factor must implement this interface:

```python
class BaseFactor:
    # ── Metadata ──
    name: str              # "Momentum_3M"
    version: str           # "2.3"
    category: str          # "Momentum" | "Value" | "Quality" | "Growth" | "Risk"
    frequency: str         # "Daily" | "Weekly" | "Monthly"
    lookback: int          # 60 (trading days)
    direction: str         # "Positive" | "Negative"
    author: str            # "Wei"
    description: str       # "3-month price momentum"
    
    # ── Processing config ──
    neutralize: list[str]  # ["Industry", "MarketCap"]
    winsorize: str         # "MAD"
    normalize: str         # "ZScore"
    
    # ── Core methods ──
    def compute(self, data_map: dict) -> pl.DataFrame: ...
    def required_columns(self) -> list[str]: ...
    def validate_input(self, df: pl.DataFrame) -> bool: ...
```

**Every factor must produce exactly**: `[trade_date, symbol, score]`. Nothing else. No Buy/Sell signal. No Position. No Portfolio logic.

---

## 7. Data Flow

```
Raw Market Data
    │
    ▼
Factor Compute Engine        ← compute_all_factors()
    │                           One pass per stock, vectorized
    ▼
Raw Factor Matrix             ← {date: {symbol: {factor: value}}}
    │
    ▼
Factor Refinery Engine        ← factor_pipeline()
    │                           Winsorize → Normalize → Neutralize → Combine
    ▼
Clean Factor Matrix           ← [trade_date, symbol, score]
    │
    ├──────────────────┐
    ▼                  ▼
Factor Store       Factor Health Engine
    │                  │
    │                  ├── IC rolling 30d/90d/252d
    │                  ├── IC IR
    │                  ├── Coverage / Missing Rate
    │                  ├── Turnover
    │                  ├── Monotonicity
    │                  ├── IC Decay Rate
    │                  └── PSI Drift
    │                  │
    ▼                  ▼
Feature Matrix     Health Report
    │                  │
    └────────┬─────────┘
             ▼
    Model Training / Strategy
             │
             ▼
    Portfolio Construction
             │
             ▼
    Risk Control
             │
             ▼
    Decision Package
```

---

## 8. Engineering Principles

| Principle | Description |
|-----------|-------------|
| **Single Responsibility** | Each component performs one well-defined task. Compute doesn't evaluate. Store doesn't monitor. |
| **Loose Coupling** | Factors, preprocessing, storage, validation, and models evolve independently. |
| **Deterministic Outputs** | Identical inputs and versions must always produce identical outputs. |
| **Version Everything** | Factors, datasets, preprocessing logic, and feature matrices are all versioned. |
| **Research First** | Factors produce standardized numerical signals only; all investment decisions are made by downstream strategy and portfolio layers. |
| **Continuous Validation** | Every factor is continuously monitored and re-evaluated throughout its lifecycle. |
| **Scalable by Design** | The architecture supports parallel computation and incremental expansion from a handful of factors to hundreds without redesign. |

---

## 9. Relationship to Existing QP Architecture

This DP formalizes the Factor Pipeline as a subsystem within Layer 3 (Research Layer). It builds on and integrates with:

| QP Component | DP Reference | Status |
|-------------|-------------|--------|
| `qp/research/feature/compute.py` | §4.1 Factor Compute Engine | ✅ Implemented (18 factors) |
| `qp/research/factor_processor.py` | §4.2 Factor Refinery Engine | ✅ Implemented |
| `data/experiments/` | §4.3 Factor Store | ⚠️ Partial (raw only, no refined/feature tiers) |
| `qp/monitoring/factor_health.py` | §4.4 Factor Health Engine | ✅ Implemented |
| `qp/validation/checks/factor_checks.py` | §4.5 Validation Gate | ✅ Implemented |
| `qp/strategy/factor_layers.py` | §4.6 Feature Matrix / Combine | ✅ Implemented (FactorEnsemble v2) |
| `qp/strategy/regime_ensemble.py` | Regime → Layer Weight | ✅ Implemented |
| `qp/shared/protocols/base_feature.py` | §6 Factor Standard | ⚠️ Partial (needs metadata fields) |

### 9.1 Gaps to Close

| Gap | Priority | Description |
|-----|:--------:|-------------|
| Factor Store — refined tier | Medium | Save post-refinery factor values for audit trail |
| Factor Store — feature tier | Medium | Save feature matrix with versioned schema |
| BaseFactor metadata | High | Add version, category, lookback, direction, author fields |
| Factor Registry auto-discovery | Medium | Auto-register factors from metadata instead of manual registration |
| Validation Gate integration | Low | Wire factor health → gate → registry lifecycle automatically |

---

## 10. Implementation Checklist

### 10.1 Factor Compute Engine (§4.1)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| C1 | 18 price/volume factors (momentum, volatility, volume, money flow) | ✅ Done | — | `qp/research/feature/compute.py` |
| C2 | Residual_Momentum_3M (beta-adjusted) | ✅ Done | — | `qp/research/feature/momentum.py` |
| C3 | Quality factors (ROE_Level, Profit_Stability, Earnings_Quality, Margin_Composite) | ✅ Done | — | `qp/research/feature/quality.py` |
| C4 | `compute_all_factors()` subset parameter (bottleneck fix) | ✅ Done | — | Avoids 121-day wait for unused factors |
| C5 | Per-factor IC attribution (`_compute_factor_ic_attribution`) | ✅ Done | — | `qp/pipeline/multifactor_pipeline.py` |
| C6 | Individual factor classes follow `BaseFeature` protocol | ✅ Done | — | 15/18 + quality factors have full metadata now |
| C7 | Factor metadata (version, category, lookback, direction, author) | ✅ Done | — | 10 fields on BaseFeature with sensible defaults |
| C8 | Auto-registration from factor metadata | ✅ Done | — | `FeatureRegistry.auto_register_all()` + `register_from_metadata()` |

### 10.2 Factor Refinery Engine (§4.2)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| R1 | Winsorize (MAD + Percentile) | ✅ Done | — | `qp/research/factor_processor.py` |
| R2 | Normalize (Rank, ZScore, MinMax) | ✅ Done | — | |
| R3 | Industry Neutralization (OLS + Median) | ✅ Done | — | |
| R4 | Factor Orthogonalization (VIF-based) | ✅ Done | — | |
| R5 | `factor_pipeline()` orchestration | ✅ Done | — | |
| R6 | Regime-aware weight selection in pipeline | ✅ Done | — | `regime_weights` + `regime_map` params |
| R7 | Market Cap Neutralization (OLS) | ✅ Done | — | Via `market_cap_map` param |
| R8 | Missing value handling — cross-sectional median fill | ✅ Done | — | `fill_cross_sectional_median()` in factor_processor.py |

### 10.3 Factor Store (§4.3)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| S1 | Raw factor persistence (experiment snapshots) | ✅ Done | — | `data/experiments/*.json` + parquet |
| S2 | Refined tier — post-refinery factor values | ✅ Done | — | `FactorStore.save_refined()` at `data/factor_store/` |
| S3 | Feature tier — versioned feature matrix | ✅ Done | — | `FactorStore.save_feature_matrix()` |
| S4 | Store metadata (version, date_range, hash, row_count) | ✅ Done | — | `TierMetadata` dataclass |
| S5 | Three-tier directory structure (`raw/` `refined/` `feature/`) | ✅ Done | — | `FactorStore.ensure_dirs()` |

### 10.4 Factor Health Engine (§4.4)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| H1 | `FactorHealthMonitor` — per-factor IC + decay detection | ✅ Done | — | `qp/monitoring/factor_health.py` |
| H2 | HEALTHY / WARNING / DEGRADED / STALE classification | ✅ Done | — | |
| H3 | Rolling IC windows (30d / 90d / 252d) | ✅ Done | — | |
| H4 | IC decay rate (linear regression slope) | ✅ Done | — | |
| H5 | `FactorHealthLogger` — Parquet persistence | ✅ Done | — | `data/monitoring/factor_health.parquet` |
| H6 | `FactorHealthPipeline` — daily monitoring integration | ✅ Done | — | Integrated into `KillSwitchPipeline` |
| H7 | PSI drift detection per factor | ✅ Done | — | `FactorHealthMonitor.compute_psi()` + `check_psi_for_factor()` |
| H8 | Factor crowding / HHI monitoring | ✅ Done | — | `compute_crowding_hhi()` |
| H9 | Factor turnover monitoring (day-over-day rank correlation) | ✅ Done | — | `compute_turnover()` + `compute_rolling_turnover()` |
| H10 | Auto weight reduction on DEGRADED/STALE | ✅ Done | — | `get_active_weights_with_health()` in FactorEnsemble |
| H11 | Web dashboard — `/health/factors` | ✅ Done | — | Factor health table + per-factor IC charts |

### 10.5 Validation Gate (§4.5)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| V1 | Rank IC Check (\|IC\| ≥ 0.02) | ✅ Done | — | `qp/validation/checks/factor_checks.py` |
| V2 | IC IR Check (≥ 0.30) | ✅ Done | — | |
| V3 | IC t-stat Check (≥ 2.0) | ✅ Done | — | |
| V4 | Stratification Check (Q5-Q1 spread t-stat ≥ 2.0) | ✅ Done | — | |
| V5 | Neutralization Survival Check (post/pre IC ≥ 0.5) | ✅ Done | — | |
| V6 | Min Sample Period Check (≥ 3 years) | ✅ Done | — | |
| V7 | Coverage Check (> 95%) | ✅ Done | — | `CoverageCheck` in factor_checks.py |
| V8 | Missing Rate Check (< 5%) | ✅ Done | — | `MissingRateCheck` in factor_checks.py |
| V9 | Max Correlation Check (< 0.85 with existing factors) | ✅ Done | — | `MaxCorrelationCheck` in factor_checks.py |
| V10 | Turnover Limit Check | ✅ Done | — | `TurnoverLimitCheck` in factor_checks.py |
| V11 | Gate → Registry lifecycle wiring (PASS → Available, FAIL → Deprecated) | ✅ Done | — | `gate_registry_bridge.py` — auto lifecycle transitions |

### 10.6 Factor Layer v2 / Ensemble (§4.6)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| E1 | `FactorEnsemble` — 4-layer structure (Price/Value/Quality/Growth) | ✅ Done | — | `qp/strategy/factor_layers.py` |
| E2 | `REGIME_LAYER_WEIGHTS` — 6 regime → layer weight mapping | ✅ Done | — | `qp/strategy/regime_ensemble.py` |
| E3 | `alpha_ensemble_v2` strategy registration | ✅ Done | — | `qp/strategy/strategies/ensemble_v2.py` |
| E4 | Regime-aware per-date weight selection in `factor_pipeline` | ✅ Done | — | Via `regime_weights` + `regime_map` |
| E5 | Pipeline regime detection → ensemble integration | ✅ Done | — | `MarketRegimeDetector` in `_run_full_strategy` |
| E6 | Factor Layer Catalog auto-generation from metadata | ✅ Done | — | `FeatureRegistry.catalog()` |
| E7 | Layer weight optimization from IC (not just flat weights) | ✅ Done | — | `FactorEnsemble.optimize_layer_weights_from_ic()` |
| E8 | Regime detection quality audit (distribution sanity check) | ✅ Done | — | Logging + Counter-based distribution check |

### 10.7 Factor Standard (§6)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| F1 | `name`, `version`, `category`, `lookback`, `direction` metadata fields | ✅ Done | — | 10 properties on `BaseFeature` ABC + concrete |
| F2 | `neutralize`, `winsorize`, `normalize` processing config | ✅ Done | — | Properties with defaults on BaseFeature |
| F3 | `author`, `description` documentation fields | ✅ Done | — | Properties with defaults on BaseFeature |
| F4 | `validate_input()` — schema validation on compute | ✅ Done | — | Method on both BaseFeature classes |
| F5 | All factors output exactly `[trade_date, symbol, score]` | ✅ Done | — | Enforced by `BaseFeature` protocol |
| F6 | No factor outputs Buy/Sell/Position | ✅ Done | — | Enforced by architecture |

### 10.8 Factor Lifecycle (§5)

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| L1 | Research → Implementation → Computation flow | ✅ Done | — | |
| L2 | Storage → Health Evaluation → Validation flow | ✅ Done | — | `GateRegistryBridge` + `FactorHealthMonitor.check_all()` |
| L3 | Registry → Available for Research | ✅ Done | — | `StrategyRegistry` |
| L4 | Model Training → Strategy → Monitoring → Retirement | ✅ Done | — | `check_retirement()` + auto-retirement flag |
| L5 | Auto-retirement trigger (IC below threshold for N consecutive days) | ✅ Done | — | `FactorHealthMonitor.check_retirement()` |

### 10.9 Cross-cutting

| # | Item | Status | Priority | Notes |
|:-:|------|:------:|:--------:|------|
| X1 | Benchmark calculation — filter penny stocks, cap extreme returns | ✅ Done | — | `_benchmark_return` fix |
| X2 | Experiment reproducibility (frozen weights, versioned configs) | ✅ Done | — | `freeze_weights` mode |
| X3 | `ruff check` zero errors on factor code | ✅ Done | — | |
| X4 | `pyright` zero errors on factor code | ✅ Done | — | |
| X5 | `pytest` all passing (1448 tests) | ✅ Done | — | |
| X6 | TDD documents for each component | ✅ Done | — | 32 E2E tests in `tests/integration/test_factor_pipeline_e2e.py` |
| X7 | Factor Pipeline end-to-end integration test | ✅ Done | — | 7-phase test: Compute → Refinery → Store → Health → Gate → Registry → Ensemble |

---

## 11. Document Hierarchy

```
docs/
├── Constitution/
│   └── Project_Constitution.md          ← "What the system should be"
│
├── Design_Proposal/
│   ├── DP-001_Data_Layer.md             ← Data Products, Bronze/Silver/Gold
│   ├── DP-002_Factor_Pipeline.md        ← This document
│   ├── DP-003_Strategy_Engine.md        ← Signal generation, factor combination
│   ├── DP-004_Portfolio_Risk.md         ← Position sizing, risk control
│   ├── DP-005_Capital_Allocation.md     ← Capital allocation across strategies
│   ├── DP-006_Simulation.md             ← Backtest, paper trading
│   ├── DP-007_Decision_Layer.md         ← Decision audit, explainability
│   └── DP-008_Monitoring.md             ← Kill switch, drift, model decay
│
├── Technical_Design/
│   ├── TDD-FactorCompute.md             ← compute_all_factors internals
│   ├── TDD-FactorRefinery.md            ← factor_pipeline internals
│   ├── TDD-FactorStore.md               ← Parquet schema, dedup, versioning
│   ├── TDD-HealthEngine.md              ← Rolling IC, decay detection
│   └── TDD-ValidationGate.md            ← Rule engine, gate decisions
│
└── API/
    └── ...
```

---

## 12. References

- Project Constitution v4.2 — 12-layer architecture, 28 rules
- ADR-006: Everything Is Pipeline
- ADR-013: Data Product Architecture
- ADR-019: Feature Versioning
- ADR-021: Purged KFold Mandatory
- ADR-030: Monitoring Layer — Observe Only, Never Decide
- `data/knowledge/factor-system.md` — 18-factor catalog
- `data/knowledge/factor-failure-analysis.md` — Factor failure diagnosis
