<script setup>
import { onMounted, ref, computed } from 'vue';
import { api } from '../api';

const factors = ref([]);
const updatedAt = ref('');
const err = ref('');
const catFilter = ref('all');
const kw = ref('');

const cats = ref([]);

const display = computed(() => {
  let arr = factors.value;
  if (catFilter.value !== 'all') arr = arr.filter(f => f.category === catFilter.value);
  if (kw.value.trim()) {
    const q = kw.value.trim().toLowerCase();
    arr = arr.filter(f => (f.name + ' ' + (f.description || '')).toLowerCase().includes(q));
  }
  return arr;
});

async function load() {
  try {
    const d = await api.factors();
    factors.value = d.factors;
    updatedAt.value = d.updated_at;
    cats.value = ['all', ...new Set(d.factors.map(f => f.category).filter(Boolean))];
  } catch (e) { err.value = e.message; }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5 flex-wrap gap-3">
      <h1 class="text-xl font-semibold text-slate-100">因子注册表
        <span class="text-[11px] font-normal text-slate-500 ml-2">factor_registry.json · {{ factors.length }} 个 · updated {{ (updatedAt || '').slice(0, 10) }}</span>
      </h1>
      <div class="flex items-center gap-2">
        <RouterLink to="/monitor"
          class="text-[11px] px-2.5 py-1.5 rounded-md border border-slate-700 text-slate-400 hover:text-cyan-300 hover:border-cyan-500/50 transition-colors">
          因子健康在 监控 页 →
        </RouterLink>
        <input v-model="kw" placeholder="搜索因子名/描述…"
          class="bg-slate-900 border border-slate-700 rounded-md px-3 py-1.5 text-[13px] w-52 focus:outline-none focus:border-cyan-500/50" />
        <select v-model="catFilter" class="bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-[12px]">
          <option v-for="c in cats" :key="c" :value="c">{{ c === 'all' ? '全部分类' : c }}</option>
        </select>
      </div>
    </div>

    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>

    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
      <div v-for="f in display" :key="f.name" class="card p-4 hover:border-slate-600 transition-colors">
        <div class="flex items-center justify-between mb-1.5">
          <span class="font-medium mono text-slate-100">{{ f.name }}</span>
          <span class="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">{{ f.category }}</span>
        </div>
        <div class="flex gap-3 text-[11px] mb-2">
          <span class="text-slate-500">方向
            <b :class="f.direction > 0 ? 'text-red-400' : 'text-emerald-400'">{{ f.direction > 0 ? '正向 +' : '反向 −' }}</b>
          </span>
          <span class="text-slate-500">lookback <b class="mono text-slate-300">{{ f.lookback ?? '—' }}</b></span>
          <span class="text-slate-500">数据 <b class="text-slate-300">{{ (f.required_data || []).join(',') }}</b></span>
        </div>
        <p class="text-[12px] text-slate-400 leading-relaxed min-h-8">{{ f.description || '—' }}</p>
        <div class="text-[10px] text-slate-600 mt-2 truncate" :title="f.class">{{ f.class }}</div>
      </div>
    </div>
    <div v-if="!display.length" class="card p-6 text-center text-slate-500">无匹配因子</div>
  </div>
</template>
