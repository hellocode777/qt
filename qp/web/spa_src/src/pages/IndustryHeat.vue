<script setup>
import { computed, onMounted, ref } from 'vue';
import { api, fmtPct } from '../api';

const data = ref(null);
const err = ref('');
const loading = ref(false);
const source = ref(''); // '' = 最新快照 / 'price' / 'capital_flow'
const showAll = ref(false);

const rows = computed(() => {
  const r = data.value?.rows ?? [];
  return showAll.value ? r : r.slice(0, 25);
});

// price 源不含资金流字段（值为 0 是「无该数据」而非「净流入为零」）→ 显示 —
const hasFlow = computed(() => data.value?.source === 'capital_flow');

function fmtYi(x) {
  if (x === null || x === undefined) return '—';
  return `${x >= 0 ? '+' : ''}${Number(x).toFixed(2)}`;
}

function fmtNum(x, digits = 2) {
  if (x === null || x === undefined) return '—';
  return Number(x).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// 滞后提示：0-1 天可接受；>3 天显著着色（如实，不美化）
const lagCls = computed(() => {
  const d = data.value?.data_lag_days;
  if (d === null || d === undefined) return 'text-slate-500';
  if (d <= 1) return 'text-emerald-400';
  if (d <= 3) return 'text-amber-300';
  return 'text-red-400';
});

async function load() {
  loading.value = true;
  err.value = '';
  try {
    data.value = await api.industryHeat(source.value, 200);
    if (data.value && data.value.ok === false) {
      err.value = `${data.value.error}${data.value.hint ? ' — ' + data.value.hint : ''}`;
      data.value = null;
    }
  } catch (e) {
    err.value = String(e);
    data.value = null;
  } finally {
    loading.value = false;
  }
}

function pick(s) {
  source.value = s;
  load();
}

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <div>
        <h1 class="text-xl font-bold text-slate-100">行业热度</h1>
        <div class="text-[11px] text-slate-500 mt-0.5">
          数据源 <code>qp industry heat --save</code> 落盘快照 · 75 个证监会行业
        </div>
      </div>
      <div class="flex items-center gap-1.5">
        <button
          v-for="s in [{ k: '', t: '最新' }, { k: 'price', t: '价格源' }, { k: 'capital_flow', t: '资金流源' }]"
          :key="s.k"
          class="px-2.5 py-1 rounded-md text-[11px] border transition-colors"
          :class="
            source === s.k
              ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
              : 'border-slate-700 text-slate-400 hover:text-slate-200'
          "
          @click="pick(s.k)"
        >
          {{ s.t }}
        </button>
        <button class="ml-2 px-2.5 py-1 rounded-md text-[11px] border border-slate-700 text-slate-400 hover:text-slate-200" @click="load">
          ↻ 刷新
        </button>
      </div>
    </div>

    <div v-if="err" class="mb-4 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-[12px] text-red-300">
      无行业热度快照：{{ err }}
    </div>

    <div v-if="loading" class="text-[12px] text-slate-500 py-6">加载中…</div>

    <template v-if="data && data.ok">
      <!-- 快照来源与滞后（如实标注，不美化） -->
      <div class="rounded-lg border border-slate-800 bg-[#0d1220] px-4 py-3 mb-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
        <div>
          <div class="text-slate-500">快照文件</div>
          <div class="text-slate-200 font-mono mt-0.5">{{ data.snapshot_file }}</div>
        </div>
        <div>
          <div class="text-slate-500">数据日 as_of / 请求日</div>
          <div class="text-slate-200 mt-0.5">{{ data.as_of ?? '—' }} / {{ data.requested_as_of ?? '—' }}</div>
        </div>
        <div>
          <div class="text-slate-500">底层价格数据末日</div>
          <div class="text-slate-200 mt-0.5">{{ data.data_date_max ?? '—' }}</div>
        </div>
        <div>
          <div class="text-slate-500">滞后</div>
          <div class="mt-0.5" :class="lagCls">
            快照 {{ data.lag_days ?? '—' }} 天 · 底层数据 {{ data.data_lag_days ?? '—' }} 天
          </div>
        </div>
      </div>

      <div class="text-[11px] text-slate-500 mb-2">
        源 <span class="text-slate-300">{{ data.source ?? '—' }}</span> ·
        窗口 <span class="text-slate-300">{{ data.window ?? '—' }}</span> 日 ·
        粒度 <span class="text-slate-300">{{ data.granularity ?? '—' }}</span> ·
        行业数 <span class="text-slate-300">{{ data.n_industries }}</span>
        <span v-if="data.other_members"> · 未归类成员 {{ data.other_members }}</span>
        <span v-if="!hasFlow" class="text-amber-300">
          · 价格源不含资金流字段（下方资金流列显示 — 而非 0）
        </span>
      </div>

      <table class="w-full text-[12px] border border-slate-800 rounded-lg overflow-hidden">
        <thead class="bg-slate-900/60 text-slate-400">
          <tr>
            <th class="text-left px-3 py-2 font-medium">行业</th>
            <th class="text-right px-3 py-2 font-medium">成员</th>
            <th class="text-right px-3 py-2 font-medium">涨跌幅</th>
            <th class="text-right px-3 py-2 font-medium">上涨占比</th>
            <th class="text-right px-3 py-2 font-medium">主力净流入(亿)</th>
            <th class="text-right px-3 py-2 font-medium">成交额(亿)</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.industry" class="border-t border-slate-800/70 hover:bg-slate-800/30">
            <td class="px-3 py-1.5 text-slate-200">{{ r.industry }}</td>
            <td class="px-3 py-1.5 text-right text-slate-400">{{ r.members ?? '—' }}</td>
            <td class="px-3 py-1.5 text-right" :class="r.change_pct > 0 ? 'text-red-400' : r.change_pct < 0 ? 'text-emerald-400' : 'text-slate-400'">
              {{ fmtPct(r.change_pct) }}
            </td>
            <td class="px-3 py-1.5 text-right text-slate-300">
              {{ r.up_ratio === null || r.up_ratio === undefined ? '—' : r.up_ratio.toFixed(1) + '%' }}
            </td>
            <td class="px-3 py-1.5 text-right" :class="hasFlow ? (r.main_net_flow_yi > 0 ? 'text-red-400' : r.main_net_flow_yi < 0 ? 'text-emerald-400' : 'text-slate-400') : 'text-slate-600'">
              {{ hasFlow ? fmtYi(r.main_net_flow_yi) : '—' }}
            </td>
            <td class="px-3 py-1.5 text-right text-slate-400">{{ fmtNum(r.amount_yi) }}</td>
          </tr>
        </tbody>
      </table>

      <div class="mt-2 flex items-center justify-between text-[11px] text-slate-500">
        <span>显示 {{ rows.length }} / {{ data.n_industries }} 个行业（快照内原始排序，未重排）</span>
        <button v-if="data.rows.length > 25" class="text-cyan-400 hover:text-cyan-300" @click="showAll = !showAll">
          {{ showAll ? '收起' : '展开全部' }}
        </button>
      </div>
    </template>
  </div>
</template>
