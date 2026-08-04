# WebUI 图表系统实现跟踪

> 创建: 2026-08-04 | 状态: 规划中

## 目标

将当前散落的 Canvas 图表代码重构为结构化图表系统，标准化数据格式，修复实验页面图表 bug。

---

## Step 1 — 标准化 Parquet Schema

**影响文件**: `qp/pipeline/multifactor_pipeline.py`

### 当前状态

```python
# _compute_backtest() 返回
"daily_equity": daily_equity,       # list[float]
"daily_dates": [str(d) for d in all_dates],  # list[str]

# 快照保存
nav_df = pl.DataFrame({
    "date": daily_dates,
    "equity": [round(e, 2) for e in daily_equity_list],
})
```

缺少: benchmark 曲线、日收益率、回撤序列。

### 目标状态

```python
# daily_nav.parquet schema
nav_df = pl.DataFrame({
    "date": daily_dates,
    "portfolio_value": [...],    # 每日组合净值
    "benchmark_value": [...],    # 等权全市场基准
    "daily_return": [...],       # 日收益率 (小数)
    "drawdown": [...],           # 回撤百分比 (正数，如 13.6 表示 -13.6%)
})
```

### 改动要点

1. **`_compute_backtest()` 循环内** (line ~1232-1432):
   - 每日计算 benchmark 净值 (等权全市场 buy-and-hold)
   - 每日计算 drawdown (从 running max 到当前的回撤百分比)
   - 返回 `daily_benchmark: list[float]`, `daily_drawdown: list[float]`

2. **快照保存块** (line ~715-723):
   - 扩展 DataFrame 列
   - 从 `daily_equity` 计算 `daily_return` 序列 (r_i = eq_i / eq_{i-1} - 1)

3. **向后兼容**: 旧 `daily_nav.parquet` 文件缺少新列，router 读取时需做兼容处理。

### 验证

- [ ] `uv run qp run daily --demo` 跑通
- [ ] `data/experiments/<id>/daily_nav.parquet` 包含 5 列
- [ ] `ruff check` zero errors
- [ ] `pyright` zero errors

---

## Step 2 — Service 层封装

**影响文件**: `qp/web/services/experiment_service.py`, `qp/web/routers/experiments.py`

### 当前状态

Router `experiments.py` 直接读 Parquet:

```python
# experiments.py:389 — router 直接 import polars, 直接读文件
nav_path = exp_dir / "daily_nav.parquet"
if nav_path.exists():
    nav_df = pl.read_parquet(str(nav_path))
```

违反了分层原则 (Router 不应直接操作文件系统)。

### 目标状态

Service 提供方法，Router 只调用 Service:

```python
# experiment_service.py 新增方法
class ExperimentService:
    def get_equity_curve(self, experiment_id: str) -> dict[str, Any]:
        """返回 {dates, portfolio, benchmark, drawdown, daily_return}"""
        ...

    def get_trade_log(self, experiment_id: str) -> dict[str, Any]:
        """返回交易日志"""
        ...

    def get_trade_reconstruction(self, experiment_id: str) -> dict[str, Any]:
        """将 _reconstruct_trades() 逻辑移入此处"""
        ...
```

### 改动要点

1. **`experiment_service.py`**:
   - 新增 `get_equity_curve()` — 读 `daily_nav.parquet`，兼容新旧 schema
   - 新增 `get_trade_log()` — 读 `trade_log.parquet`
   - 迁移 `_reconstruct_trades()` 和 `_compute_feature_proxy()` 从 router 到 service
   - 缓存逻辑 (`trade_events.json`) 保持不变

2. **`experiments.py` router**:
   - 删除 `_reconstruct_trades()`, `_compute_feature_proxy()`
   - 删除 `import polars`, `import json`, `from pathlib import Path`
   - `experiment_trades()` 改为调用 `ExperimentService`
   - Router 文件减少 ~200 行

3. **新增 `simulation_service.py`** (可选):
   - 影子交易的权益曲线读取
   - 如果 simulation router 也有直接 Parquet 读取，一并清理

### 验证

- [ ] 实验列表页正常
- [ ] 实验详情页正常
- [ ] 交易明细页正常 (含权益曲线)
- [ ] 影子交易页正常
- [ ] `ruff check` zero errors
- [ ] `pyright` zero errors
- [ ] `pytest` all pass

---

## Step 3 — cockpit.js 图表模块化

**影响文件**: `qp/web/static/js/cockpit.js`

### 当前状态

`cockpit.js` (~209 行) 包含:
- Alpine.js `cockpitState` 数据组件
- Chart.js 健康度仪表盘 (只在 dashboard 页面用)
- `initEquityChart()` — 影子交易权益曲线 (Canvas)
- HTMX 事件监听

问题:
- 函数散落，无组织结构
- Canvas 绘制逻辑和页面绑定耦合
- `initEquityChart` 只能用于 simulation 页面，实验页面无法复用
- 无 drawdown 图表

### 目标状态

```
cockpit.js
├── Alpine.data('cockpitState', ...)         # 保持不变
├── Chart.js gauge (dashboard only)          # 保持不变
├── QPCharts = {
│   ├── EquityCurve(canvasId, data, opts)   # 通用权益曲线
│   └── DrawdownChart(canvasId, data, opts) # 回撤面积图
│   }
└── HTMX event bindings                      # 保持不变
```

### API 设计

```javascript
// 通用权益曲线
QPCharts.EquityCurve('equity-chart', {
    dates: ['2024-01-01', ...],
    portfolio: [100000, ...],       // 必填
    benchmark: [100000, ...],       // 可选 — 画虚线对比
}, {
    height: 300,                    // 默认 300
    showBenchmark: true,            // 默认 true
    showPoints: true,               // 默认 true (数据点 > 100 时自动隐藏)
    currency: '¥',                  // 默认 ¥
    unit: 10000,                    // 默认 10000 (显示为"万")
});

// 回撤图
QPCharts.DrawdownChart('dd-chart', {
    dates: ['2024-01-01', ...],
    drawdown: [0, -5.2, ...],       // 负值表示回撤
}, {
    height: 150,
});
```

### Canvas 绘制标准

所有图表共用的模式，提取为内部工具函数:

```javascript
// 内部工具 (不导出)
function _setupCanvas(canvasId, width, height) {
    // DPR 处理, canvas.width/height 设置
}
function _drawGrid(ctx, layout, yTicks, xLabels) {
    // Y轴网格线 + 标签
}
function _drawYAxis(ctx, layout, minV, maxV, format) {
    // Y轴标签 (¥XX万)
}
function _drawXLabels(ctx, layout, dates, maxLabels) {
    // X轴日期标签 (自动间隔)
}
function _drawLegend(ctx, items, x, y) {
    // 图例 (色块 + 文字)
}
```

### 改动要点

1. 提取 `initEquityChart` 的 Canvas 绘制逻辑为 `QPCharts.EquityCurve`
2. 新增 `QPCharts.DrawdownChart`
3. `initEquityChart` 改为调用 `QPCharts.EquityCurve` (向后兼容)
4. 保留 Chart.js gauge 代码不变 (仅 dashboard 使用)
5. 在 `DOMContentLoaded` 和 `htmx:afterSettle` 上注册

### 验证

- [ ] 影子交易页面权益曲线正常显示
- [ ] 曲线 + 基准对比线 + 数据点
- [ ] 鼠标悬停 tooltip
- [ ] HTMX 导航后图表正确重绘
- [ ] 实验交易明细页面权益曲线正常 (Step 4)

---

## Step 4 — 修复实验页面图表

**影响文件**: `qp/web/templates/experiment_trades.html`, `qp/web/routers/experiments.py`

### 当前状态

实验交易明细页面的权益曲线使用 div sparkline (蓝色竖线):

```javascript
// experiment_trades.html:64-68 — div bars, not Canvas
barsHTML += '<div style="position:absolute;bottom:' + padB + 'px;left:'
    + (padL + i / n * chartW) + 'px;height:' + Math.round(h)
    + 'px;width:3px;background:#2563eb;"></div>';
```

问题:
1. Div sparkline 简陋，无 Y轴标签、无网格、无 tooltip
2. 之前 Canvas API 在该页面完全不渲染 (debug 文字确认 JS 执行但 Canvas 空白)
3. 和 simulation 页面两套代码，维护成本高

### 根因分析 (Canvas 不渲染)

可能原因:
- HTMX 加载时 container `display:none` → `canvas.clientWidth = 0`
- Canvas 尺寸计算时 container 尚未完成布局
- 解决: 使用 `ResizeObserver` 或在 `requestAnimationFrame` 后初始化

### 目标状态

统一使用 `QPCharts.EquityCurve`:

```html
<!-- experiment_trades.html -->
<canvas id="equity-chart" style="width:100%;height:300px;"></canvas>

<script>
document.addEventListener('DOMContentLoaded', function() {
    var data = JSON.parse(document.getElementById('equity-data').textContent);
    QPCharts.EquityCurve('equity-chart', {
        dates: data.map(function(d) { return d.date; }),
        portfolio: data.map(function(d) { return d.equity; }),
        benchmark: data[0].benchmark ? data.map(function(d) { return d.benchmark; }) : null,
    });
});
</script>
```

### 改动要点

1. 替换 experiment_trades.html 的 div sparkline 为 `<canvas>` + `QPCharts.EquityCurve`
2. 数据通过 `<script type="application/json" id="equity-data">` 注入 (沿用现有模式)
3. 注册 `htmx:afterSettle` 事件确保 HTMX 导航后重绘
4. Canvas 初始化前检查 `canvas.clientWidth > 0`
5. Router 返回的数据格式与 `QPCharts.EquityCurve` 对齐

### 验证

- [ ] 实验交易明细页面: Canvas 权益曲线可见
- [ ] 蓝色实线 (组合净值) + 绿色虚线 (基准)
- [ ] Y轴标签 (¥XX万)
- [ ] X轴日期标签
- [ ] 刷新页面后图表正确
- [ ] HTMX 导航后图表正确
- [ ] 无 JS console 错误

---

## 验证清单 (全量)

每个 Step 完成后运行:

```bash
uv sync --extra dev
uv run ruff format && uv run ruff check && uv run pyright && uv run pytest
uv run qp run daily --demo
```

WebUI 手动验证:

| 页面 | 权益曲线 | 基准对比 | 回撤图 | 响应式 | HTMX导航 |
|------|---------|---------|--------|--------|----------|
| 影子交易 /simulation | ✅ | ✅ | — | ✅ | ✅ |
| 交易明细 /experiments/{id}/trades | ✅ | ✅ | — | ✅ | ✅ |

---

## 进度

| Step | 描述 | 状态 | 完成时间 |
|------|------|------|----------|
| 1 | 标准化 Parquet Schema | ⬜ 待开始 | — |
| 2 | Service 层封装 | ⬜ 待开始 | — |
| 3 | cockpit.js 图表模块化 | ⬜ 待开始 | — |
| 4 | 修复实验页面图表 | ⬜ 待开始 | — |
