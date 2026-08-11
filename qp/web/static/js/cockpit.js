/* ===================================================================
   QP Decision Cockpit — Alpine.js state + Chart.js gauge + QPCharts
   =================================================================== */

// ---------------------------------------------------------------------------
// Alpine.js: global cockpit state
// ---------------------------------------------------------------------------
document.addEventListener('alpine:init', () => {
  Alpine.data('cockpitState', () => ({
    killSwitchLevel: 'NORMAL',
    init() {
      const ksEl = document.querySelector('[data-ks-level]');
      if (ksEl) {
        this.killSwitchLevel = ksEl.dataset.ksLevel;
      }
    },
  }));
});

// ---------------------------------------------------------------------------
// Chart.js: health score doughnut gauge (dashboard only)
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('healthGauge');
  if (!canvas) return;

  const card = canvas.closest('[x-data]');
  let score = 100;
  if (card) {
    const alpineData = card._x_dataStack?.[0];
    if (alpineData?.score !== undefined) {
      score = alpineData.score;
    }
  }

  const getColor = (s) => {
    if (s >= 80) return '#2e7d32';
    if (s >= 60) return '#f57f17';
    if (s >= 40) return '#e65100';
    return '#c62828';
  };

  new Chart(canvas, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [score, Math.max(0, 100 - score)],
        backgroundColor: [getColor(score), '#e0e0e0'],
        borderWidth: 0,
        circumference: 270,
        rotation: 225,
      }],
    },
    options: {
      cutout: '75%',
      plugins: {
        tooltip: { enabled: false },
        legend: { display: false },
      },
      responsive: false,
    },
  });
});

// HTMX config
document.addEventListener('htmx:configRequest', () => {
  // Ready for future headers
});

// ===========================================================================
// QPCharts — reusable Canvas 2D chart library
// ===========================================================================

var QPCharts = (function () {
  'use strict';

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  /**
   * Setup canvas for HiDPI rendering.
   * Returns {ctx, W, H, dpr} with CSS size set and canvas buffer scaled.
   */
  function _setupCanvas(canvas, opts) {
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width || 800;
    var H = opts.height || 300;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    return { ctx: ctx, W: W, H: H, dpr: dpr };
  }

  /**
   * Format a numeric value using currency + unit.
   */
  function _fmtVal(v, opts) {
    var u = (opts.unit || 10000);
    var sym = (opts.currency || '¥');
    var label = (opts.unitLabel || '万');
    return sym + (v / u).toFixed(1) + label;
  }

  /**
   * Draw horizontal grid lines + Y-axis labels.
   */
  function _drawYGrid(ctx, pad, W, H, minV, maxV, opts) {
    var nGrid = 4;
    var ph = H - pad.top - pad.bottom;
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#6b7280';
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'right';

    for (var g = 0; g <= nGrid; g++) {
      var gy = pad.top + (g / nGrid) * ph;
      ctx.beginPath();
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(W - pad.right, gy);
      ctx.stroke();

      var gv = maxV - (g / nGrid) * (maxV - minV);
      ctx.fillText(_fmtVal(gv, opts), pad.left - 6, gy + 4);
    }
  }

  /**
   * Draw X-axis date labels (auto-spaced).
   */
  function _drawXLabels(ctx, pad, W, H, dates, maxLabels) {
    maxLabels = maxLabels || 7;
    var n = dates.length;
    var step = Math.max(1, Math.ceil(n / maxLabels));
    ctx.textAlign = 'center';
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px sans-serif';
    var pw = W - pad.left - pad.right;
    var labelY = pad.top + (H - pad.top - pad.bottom) + 20;

    for (var i = 0; i < n; i += step) {
      var x = pad.left + (i / Math.max(n - 1, 1)) * pw;
      var d = dates[i];
      if (d && d.length >= 10) d = d.substring(0, 10);
      ctx.fillText(d, x, labelY);
    }
    // Always show last date
    if (n > 1 && (n - 1) % step !== 0) {
      var lx = pad.left + pw;
      var ld = dates[n - 1];
      if (ld && ld.length >= 10) ld = ld.substring(0, 10);
      ctx.fillText(ld, lx, labelY);
    }
  }

  /**
   * Draw a legend row.
   */
  function _drawLegend(ctx, items, x, y) {
    items.forEach(function (item) {
      ctx.fillStyle = item.color;
      ctx.fillRect(x, y, 12, 12);
      ctx.fillStyle = '#374151';
      ctx.font = '12px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(item.label, x + 16, y + 11);
      x += ctx.measureText(item.label).width + 36;
    });
  }

  /**
   * Compute nice value range with padding.
   */
  function _valueRange(seriesList, padPct) {
    padPct = padPct || 0.1;
    var allVals = [];
    seriesList.forEach(function (s) {
      if (s) allVals = allVals.concat(s);
    });
    if (!allVals.length) return { min: 0, max: 1000 };
    var minV = Math.min.apply(null, allVals);
    var maxV = Math.max.apply(null, allVals);
    var range = maxV - minV || Math.abs(maxV) * 0.02 || 1000;
    return {
      min: minV - range * padPct,
      max: maxV + range * padPct,
    };
  }

  /**
   * Y coordinate from value.
   */
  function _y(val, pad, H, minV, maxV) {
    var ph = H - pad.top - pad.bottom;
    return pad.top + ph - ((val - minV) / (maxV - minV)) * ph;
  }

  /**
   * X coordinate from index.
   */
  function _x(i, n, pad, W) {
    var pw = W - pad.left - pad.right;
    return pad.left + (i / Math.max(n - 1, 1)) * pw;
  }

  // -----------------------------------------------------------------------
  // Tooltip support
  // -----------------------------------------------------------------------
  var _tooltipEl = null;

  function _ensureTooltip() {
    if (_tooltipEl) return _tooltipEl;
    _tooltipEl = document.createElement('div');
    _tooltipEl.id = 'qp-chart-tooltip';
    _tooltipEl.style.cssText =
      'position:fixed;display:none;background:rgba(0,0,0,0.8);color:#fff;' +
      'padding:6px 10px;border-radius:4px;font-size:12px;font-family:monospace;' +
      'pointer-events:none;z-index:9999;white-space:nowrap;';
    document.body.appendChild(_tooltipEl);
    return _tooltipEl;
  }

  function _showTooltip(ev, html) {
    var tip = _ensureTooltip();
    tip.innerHTML = html;
    tip.style.display = 'block';
    tip.style.left = (ev.clientX + 12) + 'px';
    tip.style.top = (ev.clientY - 28) + 'px';
  }

  function _hideTooltip() {
    if (_tooltipEl) _tooltipEl.style.display = 'none';
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /**
   * EquityCurve — portfolio equity vs benchmark line chart.
   *
   * Usage:
   *   QPCharts.EquityCurve('equity-chart', {
   *       dates:   ['2024-01-01', ...],
   *       portfolio: [100000, ...],
   *       benchmark: [100000, ...],   // optional
   *   }, {
   *       height: 300,
   *       showBenchmark: true,
   *       currency: '¥',
   *       unit: 10000,
   *       unitLabel: '万',
   *   });
   */
  function EquityCurve(canvasId, data, opts) {
    opts = opts || {};
    if (opts.showBenchmark === undefined) opts.showBenchmark = true;
    if (!opts.currency) opts.currency = '¥';
    if (!opts.unit) opts.unit = 10000;
    if (!opts.unitLabel) opts.unitLabel = '万';
    if (!opts.height) opts.height = 300;

    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Avoid duplicate draws
    if (canvas._qpDrawn) return;
    canvas._qpDrawn = true;

    var dates = data.dates || [];
    var portfolio = data.portfolio || [];
    var benchmark = data.benchmark || null;

    if (!dates.length || !portfolio.length) return;

    var setup = _setupCanvas(canvas, opts);
    var ctx = setup.ctx, W = setup.W, H = setup.H;

    var pad = { top: 20, right: 20, bottom: 40, left: 65 };

    // Value range
    var series = [portfolio];
    if (benchmark && opts.showBenchmark) series.push(benchmark);
    var vr = _valueRange(series, 0.1);

    // Background
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    // Grid
    _drawYGrid(ctx, pad, W, H, vr.min, vr.max, opts);

    // X labels
    _drawXLabels(ctx, pad, W, H, dates, 7);

    // Draw benchmark first (behind)
    if (benchmark && opts.showBenchmark) {
      ctx.strokeStyle = '#10b981';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      for (var i = 0; i < benchmark.length; i++) {
        var bx = _x(i, benchmark.length, pad, W);
        var by = _y(benchmark[i], pad, H, vr.min, vr.max);
        if (i === 0) ctx.moveTo(bx, by);
        else ctx.lineTo(bx, by);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Draw portfolio line
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var j = 0; j < portfolio.length; j++) {
      var px = _x(j, portfolio.length, pad, W);
      var py = _y(portfolio[j], pad, H, vr.min, vr.max);
      if (j === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // Data points (skip if > 200 points)
    var showPoints = portfolio.length <= 200;
    if (showPoints) {
      for (var k = 0; k < portfolio.length; k++) {
        var dx = _x(k, portfolio.length, pad, W);
        var dy = _y(portfolio[k], pad, H, vr.min, vr.max);
        ctx.fillStyle = '#2563eb';
        ctx.beginPath();
        ctx.arc(dx, dy, portfolio.length === 1 ? 5 : 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Legend
    var legendItems = [
      { color: '#2563eb', label: '组合净值 Portfolio' },
    ];
    if (benchmark && opts.showBenchmark) {
      legendItems.push({ color: '#10b981', label: '等权基准 Benchmark' });
    }
    _drawLegend(ctx, legendItems, pad.left, 10);

    // ── Hover tooltip ──
    canvas._qpData = { dates: dates, portfolio: portfolio, benchmark: benchmark,
                        pad: pad, vr: vr, opts: opts, n: portfolio.length };
    canvas.addEventListener('mousemove', function (ev) {
      var d = canvas._qpData;
      if (!d) return;
      var rect = canvas.getBoundingClientRect();
      var mx = ev.clientX - rect.left;
      // Find nearest data point by X
      var idx = Math.round((mx - d.pad.left) / (W - d.pad.left - d.pad.right) * (d.n - 1));
      idx = Math.max(0, Math.min(d.n - 1, idx));
      // Full numbers in tooltip; Y-axis grid keeps the compact 万 label.
      var cur = d.opts.currency || '¥';
      var html = '<b>' + d.dates[idx].substring(0, 10) + '</b><br>' +
        '组合: ' + cur + Number(d.portfolio[idx]).toLocaleString();
      if (d.benchmark) {
        html += '<br>基准: ' + cur + Number(d.benchmark[idx]).toLocaleString();
      }
      _showTooltip(ev, html);
    });
    canvas.addEventListener('mouseleave', _hideTooltip);
  }

  /**
   * DrawdownChart — drawdown area chart (%).
   *
   * Usage:
   *   QPCharts.DrawdownChart('dd-chart', {
   *       dates: ['2024-01-01', ...],
   *       drawdown: [0, -5.2, ...],   // negative = drawdown
   *   }, { height: 150 });
   */
  function DrawdownChart(canvasId, data, opts) {
    opts = opts || {};
    if (!opts.height) opts.height = 150;

    var canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (canvas._qpDrawn) return;
    canvas._qpDrawn = true;

    var dates = data.dates || [];
    var dd = data.drawdown || [];
    if (!dates.length || !dd.length) return;

    var setup = _setupCanvas(canvas, opts);
    var ctx = setup.ctx, W = setup.W, H = setup.H;

    var pad = { top: 10, right: 20, bottom: 35, left: 50 };

    // Y range: min(dd, 0) to 0 (or a bit for positive values)
    var minDD = Math.min.apply(null, dd.concat([0]));
    var maxDD = Math.max.apply(null, dd.concat([0]));
    var range = Math.max(Math.abs(minDD), Math.abs(maxDD), 5);
    var yMin = -range * 1.15;
    var yMax = range * 0.15;

    // Background
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    // Y grid (%)
    var nGrid = 4;
    var ph = H - pad.top - pad.bottom;
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    for (var g = 0; g <= nGrid; g++) {
      var gy = pad.top + (g / nGrid) * ph;
      ctx.beginPath();
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(W - pad.right, gy);
      ctx.stroke();
      var gv = yMax - (g / nGrid) * (yMax - yMin);
      ctx.fillText(gv.toFixed(1) + '%', pad.left - 6, gy + 4);
    }

    // Zero line
    var zeroY = _y(0, pad, H, yMin, yMax);
    ctx.strokeStyle = '#9ca3af';
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, zeroY);
    ctx.lineTo(W - pad.right, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);

    // X labels
    _drawXLabels(ctx, pad, W, H, dates, 5);

    // Drawdown filled area
    ctx.beginPath();
    var firstX = _x(0, dd.length, pad, W);
    ctx.moveTo(firstX, zeroY);
    for (var i = 0; i < dd.length; i++) {
      var dx = _x(i, dd.length, pad, W);
      var dy = _y(dd[i], pad, H, yMin, yMax);
      ctx.lineTo(dx, dy);
    }
    var lastX = _x(dd.length - 1, dd.length, pad, W);
    ctx.lineTo(lastX, zeroY);
    ctx.closePath();

    // Red gradient fill
    var grad = ctx.createLinearGradient(0, pad.top, 0, zeroY);
    grad.addColorStop(0, 'rgba(220, 38, 38, 0.3)');
    grad.addColorStop(1, 'rgba(220, 38, 38, 0.05)');
    ctx.fillStyle = grad;
    ctx.fill();

    // Drawdown line
    ctx.strokeStyle = '#dc2626';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (var j = 0; j < dd.length; j++) {
      var lx = _x(j, dd.length, pad, W);
      var ly = _y(dd[j], pad, H, yMin, yMax);
      if (j === 0) ctx.moveTo(lx, ly);
      else ctx.lineTo(lx, ly);
    }
    ctx.stroke();

    // ── Hover tooltip ──
    canvas._qpData = { dates: dates, dd: dd, pad: pad, vr: { min: yMin, max: yMax }, n: dd.length };
    canvas.addEventListener('mousemove', function (ev) {
      var d = canvas._qpData;
      if (!d) return;
      var rect = canvas.getBoundingClientRect();
      var mx = ev.clientX - rect.left;
      var idx = Math.round((mx - d.pad.left) / (W - d.pad.left - d.pad.right) * (d.n - 1));
      idx = Math.max(0, Math.min(d.n - 1, idx));
      var html = '<b>' + d.dates[idx].substring(0, 10) + '</b><br>' +
        '回撤: ' + (-d.dd[idx]).toFixed(2) + '%';
      _showTooltip(ev, html);
    });
    canvas.addEventListener('mouseleave', _hideTooltip);
  }

  // -----------------------------------------------------------------------
  // Export public API
  // -----------------------------------------------------------------------
  return {
    EquityCurve: EquityCurve,
    DrawdownChart: DrawdownChart,
    // Expose for debug
    _valueRange: _valueRange,
  };
})();

// ===========================================================================
// Page-level chart initializers (backward compatible)
// ===========================================================================

/**
 * Initialize equity chart on the simulation page.
 * Reads data from <script id="equity-data" type="application/json">.
 */
function initEquityChart() {
  try {
    var canvas = document.getElementById('equityChart');
    if (!canvas) return;

    var el = document.getElementById('equity-data');
    if (!el) return;

    var rawData;
    try { rawData = JSON.parse(el.textContent || '[]'); } catch (e) { return; }
    if (!rawData || rawData.length === 0) return;

    // Map from simulation data format to QPCharts format.
    // NOTE: shadow 盘没有真实基准（等权基准只存在于实验 daily_nav），
    // 之前把 market_value 当 benchmark 传入是假基准 → 已移除，只画总权益。
    var dates = rawData.map(function (d) { return d.date; });
    var portfolio = rawData.map(function (d) { return d.total_equity; });

    QPCharts.EquityCurve('equityChart', {
      dates: dates,
      portfolio: portfolio,
      // benchmark: 不传 — shadow 无真实基准（2026-08-11 修复假基准）
    });
  } catch (e) {
    console.error('initEquityChart:', e);
  }
}

// Fire on both full page loads and HTMX navigation
document.addEventListener('DOMContentLoaded', initEquityChart);
document.addEventListener('htmx:afterSettle', initEquityChart);

// ---------------------------------------------------------------------------
// Experiment page charts (equity curve + drawdown)
// ---------------------------------------------------------------------------
function initExperimentCharts() {
  try {
    var el = document.getElementById('equity-data');
    if (!el) return;

    var rawData;
    try { rawData = JSON.parse(el.textContent || '[]'); } catch (e) { return; }
    if (!rawData || rawData.length === 0) return;

    var dates = rawData.map(function (d) { return d.date; });
    var portfolio = rawData.map(function (d) { return d.equity; });
    var hasBench = rawData.some(function (d) { return d.benchmark !== undefined; });
    var benchmark = hasBench ? rawData.map(function (d) { return d.benchmark; }) : null;
    var hasDD = rawData.some(function (d) { return d.drawdown !== undefined; });
    var drawdown = hasDD ? rawData.map(function (d) { return -d.drawdown; }) : null;

    // Reset draw guards (new canvases on each navigation)
    var eqCanvas = document.getElementById('experiment-equity-chart');
    var ddCanvas = document.getElementById('experiment-dd-chart');
    if (eqCanvas) eqCanvas._qpDrawn = false;
    if (ddCanvas) ddCanvas._qpDrawn = false;

    QPCharts.EquityCurve('experiment-equity-chart', {
      dates: dates,
      portfolio: portfolio,
      benchmark: benchmark,
    });

    if (drawdown) {
      QPCharts.DrawdownChart('experiment-dd-chart', {
        dates: dates,
        drawdown: drawdown,
      });
    }
  } catch (e) {
    console.error('initExperimentCharts:', e);
  }
}

document.addEventListener('DOMContentLoaded', initExperimentCharts);
document.addEventListener('htmx:afterSettle', initExperimentCharts);
