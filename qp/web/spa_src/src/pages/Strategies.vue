<script setup>
import { onMounted, ref } from 'vue';
import { api, pnlClass } from '../api';

const strategies = ref([]);
const err = ref('');
const expanded = ref(null);

const lifecycleColor = {
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  research: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  backtest_passed: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  backtest_failed: 'bg-red-500/15 text-red-300 border-red-500/25',
  deactivated: 'bg-slate-600/30 text-slate-400 border-slate-600',
};

function toggle(s) { expanded.value = expanded.value === s.id ? null : s.id; }

function weightList(s) {
  if (!s.weights) return [];
  return Object.entries(s.weights).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
}

async function load() {
  try {
    const d = await api.strategies();
    strategies.value = d.strategies;
  } catch (e) { err.value = e.message; }
}

onMounted(load);
</script>

<template>
  <div>
    <h1 class="text-xl font-semibold text-slate-100 mb-5">策略 <span class="text-[11px] font-normal text-slate-500 ml-2">strategy_registry.json · {{ strategies.length }} 个 · 点击行展开详情</span></h1>
    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>

    <div class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-[13px]">
          <thead>
            <tr class="text-left text-slate-500 text-[11px] border-b border-slate-800 bg-slate-900/60">
              <th class="px-4 py-2">策略 ID</th><th class="px-4 py-2">生命周期</th><th class="px-4 py-2">激活</th>
              <th class="px-4 py-2 text-right">回测 IC</th><th class="px-4 py-2 text-right">Sharpe</th>
              <th class="px-4 py-2 text-right">MaxDD %</th><th class="px-4 py-2 text-right">超额收益 %</th>
              <th class="px-4 py-2">owner</th><th class="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="s in strategies" :key="s.id">
              <tr @click="toggle(s)" class="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer">
                <td class="px-4 py-2.5 mono text-slate-100">{{ s.id }}</td>
                <td class="px-4 py-2.5">
                  <span class="text-[10px] px-1.5 py-0.5 rounded border" :class="lifecycleColor[s.lifecycle] || 'bg-slate-700/40 text-slate-400 border-slate-600'">
                    {{ s.lifecycle }}</span>
                </td>
                <td class="px-4 py-2.5"><span :class="s.active ? 'text-emerald-400' : 'text-slate-500'">{{ s.active ? '●' : '○' }}</span></td>
                <td class="px-4 py-2.5 mono text-right text-slate-200">{{ s.backtest_ic ?? '—' }}</td>
                <td class="px-4 py-2.5 mono text-right text-slate-200">{{ s.backtest_sharpe ?? '—' }}</td>
                <td class="px-4 py-2.5 mono text-right" :class="pnlClass(-(s.backtest_max_dd ?? 0))">{{ s.backtest_max_dd ?? '—' }}</td>
                <td class="px-4 py-2.5 mono text-right" :class="pnlClass(s.backtest_excess_return)">{{ s.backtest_excess_return ?? '—' }}</td>
                <td class="px-4 py-2.5 text-slate-400">{{ s.owner || '—' }}</td>
                <td class="px-4 py-2.5 text-slate-500 text-right">{{ expanded === s.id ? '▴' : '▾' }}</td>
              </tr>
              <tr v-if="expanded === s.id" class="bg-slate-900/40 border-b border-slate-800/50">
                <td colspan="9" class="px-5 py-4">
                  <div class="grid grid-cols-2 lg:grid-cols-3 gap-4">
                    <div>
                      <div class="card-title mb-2">因子权重 (sorted by |w|)</div>
                      <div v-if="weightList(s).length" class="space-y-1 text-[12px] mono">
                        <div v-for="[f, w] in weightList(s)" :key="f" class="flex justify-between">
                          <span class="text-slate-400">{{ f }}</span>
                          <span :class="pnlClass(w)">{{ w >= 0 ? '+' : '' }}{{ w.toFixed(4) }}</span>
                        </div>
                      </div>
                      <div v-else class="text-[12px] text-slate-600">无权重（未上线模型）</div>
                    </div>
                    <div>
                      <div class="card-title mb-2">参数 parameters</div>
                      <div class="space-y-1 text-[12px] mono">
                        <div v-for="(v, k) in (s.parameters || {})" :key="k" class="flex justify-between">
                          <span class="text-slate-400">{{ k }}</span><span class="text-slate-200">{{ v }}</span>
                        </div>
                      </div>
                    </div>
                    <div>
                      <div class="card-title mb-2">审批 & 元数据</div>
                      <div class="text-[12px] text-slate-400 leading-relaxed">
                        approved_at: <span class="mono text-slate-300">{{ s.approved_at || '—' }}</span><br />
                        频率: {{ s.rebalance_frequency }}<br />
                        版本: {{ s.raw?.meta?.strategy_version || '—' }}<br />
                        描述: {{ s.raw?.meta?.description || '—' }}
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!strategies.length"><td colspan="9" class="px-4 py-6 text-center text-slate-500">无数据</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
