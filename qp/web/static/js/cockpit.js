/* ===================================================================
   QP Decision Cockpit — Client-side interactivity
   Alpine.js data store + Chart.js health gauge
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

// Health score gauge chart
document.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('healthGauge');
  if (!canvas) return;

  // Get score from parent Alpine component
  const card = canvas.closest('[x-data]');
  let score = 100;
  if (card) {
    const alpineData = card._x_dataStack?.[0];
    if (alpineData?.score !== undefined) {
      score = alpineData.score;
    }
  }

  const getColor = (s) => {
    if (s >= 80) return '#3fb950';
    if (s >= 60) return '#d29922';
    if (s >= 40) return '#db6d28';
    return '#f85149';
  };

  new Chart(canvas, {
    type: 'doughnut',
    data: {
      datasets: [{
        data: [score, Math.max(0, 100 - score)],
        backgroundColor: [getColor(score), 'rgba(255,255,255,0.04)'],
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

// HTMX configuration
document.addEventListener('htmx:configRequest', (evt) => {
  // Add any custom headers here in future phases
});
