import { createApp } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import App from './App.vue';
import Dashboard from './pages/Dashboard.vue';
import Paper from './pages/Paper.vue';
import Positions from './pages/Positions.vue';
import Chart from './pages/Chart.vue';
import Strategies from './pages/Strategies.vue';
import Factors from './pages/Factors.vue';
import Decisions from './pages/Decisions.vue';
import Experiments from './pages/Experiments.vue';
import SystemHealth from './pages/SystemHealth.vue';
import Simulation from './pages/Simulation.vue';
import Knowledge from './pages/Knowledge.vue';
import IndustryHeat from './pages/IndustryHeat.vue';
import './style.css';

const router = createRouter({
  // dev 时 '/' ; build 部署在 /proto/ 下时跟随 vite base
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', component: Dashboard, meta: { title: '总览' } },
    { path: '/industry', component: IndustryHeat, meta: { title: '行业热度' } },
    { path: '/paper', component: Paper, meta: { title: '模拟盘' } },
    { path: '/positions', component: Positions, meta: { title: '持仓' } },
    { path: '/chart', component: Chart, meta: { title: '行情' } },
    { path: '/strategies', component: Strategies, meta: { title: '策略' } },
    { path: '/factors', component: Factors, meta: { title: '因子' } },
    { path: '/decisions', component: Decisions, meta: { title: '决策' } },
    { path: '/experiments', component: Experiments, meta: { title: '回测' } },
    { path: '/simulation', component: Simulation, meta: { title: '影子' } },
    { path: '/monitor', component: SystemHealth, meta: { title: '监控' } },
    { path: '/knowledge', component: Knowledge, meta: { title: '复盘' } },
  ],
});

createApp(App).use(router).mount('#app');
