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
    const canvas = document.getElementById('equityChart');
    if (!canvas) return;

    // Avoid re-initializing an existing chart
    if (canvas._chart) {
      canvas._chart.destroy();
      canvas._chart = null;
    }

    const el = document.getElementById('equity-data');
    if (!el) return;

    let rawData;
    try {
      rawData = JSON.parse(el.textContent || '[]');
    } catch {
      return;
    }
    if (!rawData || rawData.length === 0) return;

    var labels = rawData.map(function(d) { return d.date; });
    var equity = rawData.map(function(d) { return d.total_equity; });
    var marketValue = rawData.map(function(d) { return d.market_value; });

    // With only 1 data point, use larger point radius so it's visible
    var isSinglePoint = rawData.length === 1;

    canvas._chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: '总权益 Total Equity',
            data: equity,
            borderColor: '#2563eb',
            backgroundColor: 'rgba(37, 99, 235, 0.1)',
            fill: isSinglePoint ? false : true,
            tension: 0.3,
            pointRadius: isSinglePoint ? 6 : 2,
            pointHoverRadius: 8,
            borderWidth: 2,
          },
          {
            label: '持仓市值 Market Value',
            data: marketValue,
            borderColor: '#10b981',
            borderDash: [4, 3],
            tension: 0.3,
            pointRadius: isSinglePoint ? 5 : 1,
            pointHoverRadius: 7,
            borderWidth: 1.5,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { position: 'top' },
          tooltip: {
            callbacks: {
              label: function(ctx) { return ctx.dataset.label + ': ¥' + Number(ctx.raw).toLocaleString(); }
            }
          }
        },
        scales: {
          x: { display: true },
          y: {
            display: true,
            ticks: { callback: function(v) { return '¥' + (v / 10000).toFixed(0) + '万'; } }
          }
        }
      }
    });
  } catch (e) {
    console.error('initEquityChart:', e);
  }
}

document.addEventListener('DOMContentLoaded', initEquityChart);
document.addEventListener('htmx:afterSettle', initEquityChart);
