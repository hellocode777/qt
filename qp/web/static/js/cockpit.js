/* ===================================================================
   QP Decision Cockpit — Chart.js health gauge
   =================================================================== */

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

// Health score gauge
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

// ---------------------------------------------------------------------------
// Equity curve chart (simulation page)
// ---------------------------------------------------------------------------
function initEquityChart() {
  try {
    var canvas = document.getElementById('equityChart');
    if (!canvas) return;

    // Avoid re-initializing
    if (canvas._drawn) return;
    canvas._drawn = true;

    var el = document.getElementById('equity-data');
    if (!el) return;

    var rawData;
    try { rawData = JSON.parse(el.textContent || '[]'); } catch(e) { return; }
    if (!rawData || rawData.length === 0) return;

    // Set canvas resolution
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.parentElement.getBoundingClientRect();
    var W = rect.width;
    var H = rect.height || 300;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    // Layout
    var pad = { top: 20, right: 20, bottom: 40, left: 60 };
    var pw = W - pad.left - pad.right;
    var ph = H - pad.top - pad.bottom;

    // Compute value range
    var vals = [];
    rawData.forEach(function(d) {
      vals.push(d.total_equity);
      vals.push(d.market_value);
    });
    var minV = Math.min.apply(null, vals);
    var maxV = Math.max.apply(null, vals);
    var range = maxV - minV || maxV * 0.02 || 1000;
    minV -= range * 0.1;
    maxV += range * 0.1;

    function x(i) { return pad.left + (i / Math.max(rawData.length - 1, 1)) * pw; }
    function y(v) { return pad.top + ph - ((v - minV) / (maxV - minV)) * ph; }

    // Background
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    // Grid lines (Y axis)
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    var nGrid = 4;
    for (var g = 0; g <= nGrid; g++) {
      var gy = pad.top + (g / nGrid) * ph;
      ctx.beginPath();
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(W - pad.right, gy);
      ctx.stroke();

      var gv = maxV - (g / nGrid) * (maxV - minV);
      ctx.fillStyle = '#6b7280';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText('¥' + (gv / 10000).toFixed(1) + '万', pad.left - 6, gy + 4);
    }

    // X labels
    ctx.textAlign = 'center';
    ctx.fillStyle = '#6b7280';
    rawData.forEach(function(d, i) {
      if (rawData.length <= 7 || i % Math.ceil(rawData.length / 7) === 0 || i === rawData.length - 1) {
        ctx.fillText(d.date, x(i), pad.top + ph + 20);
      }
    });

    // Draw line: Total Equity
    ctx.strokeStyle = '#2563eb';
    ctx.lineWidth = 2;
    ctx.beginPath();
    rawData.forEach(function(d, i) {
      var py = y(d.total_equity);
      if (i === 0) ctx.moveTo(x(i), py);
      else ctx.lineTo(x(i), py);
    });
    ctx.stroke();

    // Draw line: Market Value (dashed)
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    rawData.forEach(function(d, i) {
      var py = y(d.market_value);
      if (i === 0) ctx.moveTo(x(i), py);
      else ctx.lineTo(x(i), py);
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw points
    rawData.forEach(function(d, i) {
      var r = rawData.length === 1 ? 5 : 3;

      ctx.fillStyle = '#2563eb';
      ctx.beginPath();
      ctx.arc(x(i), y(d.total_equity), r, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = '#10b981';
      ctx.beginPath();
      ctx.arc(x(i), y(d.market_value), r - 1, 0, Math.PI * 2);
      ctx.fill();
    });

    // Legend
    var lx = pad.left;
    var ly = 8;
    ctx.fillStyle = '#2563eb';
    ctx.fillRect(lx, ly, 12, 12);
    ctx.fillStyle = '#374151';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('总权益 Total Equity', lx + 16, ly + 11);

    lx += 140;
    ctx.fillStyle = '#10b981';
    ctx.fillRect(lx, ly, 12, 12);
    ctx.fillStyle = '#374151';
    ctx.fillText('持仓市值 Market Value', lx + 16, ly + 11);

  } catch (e) {
    console.error('initEquityChart:', e);
  }
}

document.addEventListener('DOMContentLoaded', initEquityChart);
document.addEventListener('htmx:afterSettle', initEquityChart);
