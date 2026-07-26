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
