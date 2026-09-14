<script setup>
import { onMounted, ref, nextTick } from 'vue';
import { useRoute } from 'vue-router';
import * as echarts from 'echarts';
import { api } from '../api';

const route = useRoute();
const code = ref('600519');
const days = ref(365);
const input = ref('600519');
const data = ref(null);
const err = ref('');
const loading = ref(false);
// 自选 (localStorage)
const watchlist = ref(JSON.parse(localStorage.getItem('qp-watch') || '["600519","000858"]'));
// 搜索联想
const q = ref('');
const results = ref([]);
const showDrop = ref(false);
let searchTimer = null;

function saveWatch() { localStorage.setItem('qp-watch', JSON.stringify(watchlist.value)); }
function isWatched(c) { return watchlist.value.includes(c); }
function toggleWatch(c) {
  const i = watchlist.value.indexOf(c);
  if (i >= 0) watchlist.value.splice(i, 1); else watchlist.value.push(c);
  saveWatch();
}

async function onSearchInput() {
  clearTimeout(searchTimer);
  const v = q.value.trim();
  if (!v) { results.value = []; showDrop.value = false; return; }
  searchTimer = setTimeout(async () => {
    try {
      const d = await api.stockSearch(v);
      results.value = d.results || [];
      showDrop.value = true;
    } catch (e) { results.value = []; }
  }, 300);
}
function pickStock(r) {
  input.value = r.code;
  q.value = '';
  results.value = [];
  showDrop.value = false;
  submit();
}
function selQuick(c) { input.value = c; submit(); }

function calcMA(closes, n) {
  return closes.map((_, i) => {
    if (i < n - 1) return null;
    const seg = closes.slice(i - n + 1, i + 1);
    return +(seg.reduce((a, b) => a + b, 0) / n).toFixed(2);
  });
}

async function load() {
  loading.value = true;
  err.value = '';
  try {
    const d = await api.kline(code.value, days.value);
    if (d.error) { err.value = d.error; data.value = null; return; }
    data.value = d;
    await nextTick();
    draw();
  } catch (e) {
    err.value = e.message;
    data.value = null;
  } finally {
    loading.value = false;
  }
}

function draw() {
  const el = document.getElementById('kline-chart');
  if (!el || !data.value?.data?.length) return;
  const rows = data.value.data;
  const closes = rows.map(r => r.close);
  const chart = echarts.init(el);
  chart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    legend: { data: ['K线', 'MA5', 'MA10', 'MA20'], textStyle: { color: '#94a3b8' }, top: 0 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 70, right: 20, top: 32, height: '52%' },
      { left: 70, right: 20, top: '72%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: rows.map(r => r.date), axisLine: { lineStyle: { color: '#334155' } }, axisLabel: { color: '#64748b' } },
      { type: 'category', gridIndex: 1, data: rows.map(r => r.date), axisLabel: { show: false }, axisLine: { lineStyle: { color: '#334155' } } },
    ],
    yAxis: [
      { scale: true, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#1e293b' } } },
      { gridIndex: 1, axisLabel: { color: '#64748b' }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], bottom: 2, height: 16, borderColor: '#334155', textStyle: { color: '#64748b' } },
    ],
    series: [
      {
        name: 'K线', type: 'candlestick', data: rows.map(r => [r.open, r.close, r.low, r.high]),
        itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' },
      },
      { name: 'MA5', type: 'line', data: calcMA(closes, 5), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } },
      { name: 'MA10', type: 'line', data: calcMA(closes, 10), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#38bdf8' } },
      { name: 'MA20', type: 'line', data: calcMA(closes, 20), smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#a78bfa' } },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: rows.map((r, i) => ({
          value: r.volume,
          itemStyle: { color: r.close >= r.open ? 'rgba(239,68,68,.55)' : 'rgba(34,197,94,.55)' },
        })),
      },
    ],
  });
}

async function submit() {
  code.value = input.value.trim();
  if (!code.value) return;
  await load();
}

onMounted(async () => {
  const c = route.query.code;
  if (c) {
    input.value = String(c);
    code.value = String(c);
  }
  await load();
});
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5 flex-wrap gap-3">
      <h1 class="text-xl font-semibold text-slate-100">行情 K线 <span class="text-[11px] font-normal text-slate-500 ml-2">代理 qp 8080 /api/stocks/{code}/kline · 腾讯源真实数据</span></h1>
      <div class="flex items-center gap-2 flex-wrap">
        <!-- 搜索联想 -->
        <div class="relative">
          <input v-model="q" @input="onSearchInput" @blur="setTimeout(() => showDrop = false, 200)"
            placeholder="🔍 代码/名称搜索" 
            class="bg-slate-900 border border-slate-700 rounded-md px-3 py-1.5 text-[13px] w-40 focus:outline-none focus:border-cyan-500/50" />
          <div v-if="showDrop && results.length" class="absolute z-20 mt-1 w-64 max-h-64 overflow-y-auto bg-slate-900 border border-slate-700 rounded-md shadow-xl">
            <div v-for="r in results" :key="r.code" @mousedown.prevent="pickStock(r)"
              class="px-3 py-1.5 text-[12px] hover:bg-slate-800 cursor-pointer flex justify-between">
              <span class="mono text-cyan-300">{{ r.code }}</span>
              <span class="text-slate-400">{{ r.name }}</span>
            </div>
          </div>
        </div>
        <input v-model="input" @keyup.enter="submit" placeholder="股票代码, 如 600519"
          class="bg-slate-900 border border-slate-700 rounded-md px-3 py-1.5 text-[13px] mono w-36 focus:outline-none focus:border-cyan-500/50" />
        <select v-model="days" @change="load" class="bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-[12px] mono">
          <option :value="90">90天</option><option :value="365">1年</option><option :value="730">2年</option>
        </select>
        <button @click="submit" class="text-[13px] px-3 py-1.5 rounded-md bg-cyan-500/15 border border-cyan-500/30 text-cyan-300 hover:bg-cyan-500/25">
          {{ loading ? '加载中…' : '查询' }}</button>
        <button @click="toggleWatch(code)" :title="isWatched(code) ? '从自选移除' : '加入自选'"
          class="text-[13px] px-2.5 py-1.5 rounded-md border"
          :class="isWatched(code) ? 'border-amber-500/50 text-amber-300 bg-amber-500/10' : 'border-slate-700 text-slate-500 hover:text-amber-300'">
          {{ isWatched(code) ? '★' : '☆' }}</button>
      </div>
    </div>

    <div class="flex gap-2 mb-4 flex-wrap items-center">
      <span class="text-[11px] text-slate-600">自选:</span>
      <button v-for="c in watchlist" :key="c" @click="selQuick(c)"
        class="text-[11px] px-2.5 py-1 rounded border border-slate-700 text-slate-400 hover:text-cyan-300 hover:border-cyan-500/40 mono"
        :class="{ '!border-amber-500/40 !text-amber-300': String(c) === String(code) }">{{ c }}</button>
      <span v-if="!watchlist.length" class="text-[11px] text-slate-600">空 (用 ☆ 添加)</span>
    </div>

    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>
    <div v-else-if="data" class="card p-4">
      <div class="flex justify-between text-[11px] text-slate-500 mb-2">
        <span>{{ data.code }} · {{ data.count }} 根日K · 区间 {{ data.data[0]?.date }} ~ {{ data.data[data.data.length - 1]?.date }}</span>
        <span>source: qp kline (腾讯缓存)</span>
      </div>
      <div id="kline-chart" class="h-[520px]"></div>
    </div>
  </div>
</template>
