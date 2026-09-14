<script setup>
import { onMounted, ref, computed } from 'vue';
import { api } from '../api';

const cats = ref([]);          // categories from /knowledge
const curCat = ref('failure_analysis');
const items = ref([]);
const doc = ref(null);         // {meta, content, rel}
const err = ref('');
const loadingContent = ref(false);
const autoOpen = ref('failure_analysis/20260812-081733-killswitch-pause-buy-on.md');

const catLabel = {
  failure_analysis: '失败分析',
  post_mortem: '事后复盘',
  research_debt: '研究债务',
  decision_audit: '决策审计',
  experiment_summary: '实验总结',
  market_regime_notes: '市场笔记',
  _root: '系统笔记',
};

const curCatItems = computed(() => cats.value.find(c => c.category === curCat.value) || null);

async function load() {
  try {
    const d = await api.knowledge();
    cats.value = d.categories || [];
    const order = ['failure_analysis', 'post_mortem', 'research_debt', '_root'];
    cats.value.sort((a, b) => {
      const ia = order.indexOf(a.category), ib = order.indexOf(b.category);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
    const fc = cats.value.find(c => c.category === curCat.value);
    if (fc) items.value = fc.items;
    if (cats.value.length) await selectDoc(autoOpen.value);
  } catch (e) { err.value = e.message; }
}

function pickCat(c) {
  curCat.value = c.category;
  items.value = c.items;
  if (c.items.length) openDoc(c.items[0].rel);
}

async function openDoc(rel) {
  loadingContent.value = true;
  doc.value = null;
  try {
    doc.value = await api.knowledgeContent(rel);
  } catch (e) {
    doc.value = { error: e.message };
  } finally {
    loadingContent.value = false;
  }
}

function selectDoc(rel) {
  if (rel) openDoc(rel);
}

function fmtDate(iso) {
  if (!iso) return '';
  return iso.slice(0, 10);
}

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function inline(s) {
  return esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code class="text-cyan-300 bg-slate-800 px-1 rounded text-[11px]">$1</code>');
}

// mini md 渲染: #标题 / -列表 / 数字列表 / 引用 / 代码块 / 段落
function renderMd(src) {
  const lines = (src || '').split('\n');
  let html = '';
  let inCode = false;
  let listType = null; // 'ul' | 'ol' | null
  const closeList = () => {
    if (listType) { html += `</${listType}>`; listType = null; }
  };
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      closeList();
      if (inCode) { html += '</code></pre>'; inCode = false; }
      else { html += '<pre class="bg-slate-900 border border-slate-800 rounded-md p-3 overflow-x-auto text-[12px] leading-relaxed"><code>'; inCode = true; }
      continue;
    }
    if (inCode) { html += esc(line) + '\n'; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) { closeList(); const lv = Math.min(h[1].length + 1, 5); html += `<h${lv} class="text-slate-100 font-semibold mt-3 mb-1 text-[15px]">${inline(h[2])}</h${lv}>`; continue; }
    const hr = line.trim() === '---' || line.trim() === '***';
    if (hr) { closeList(); html += '<hr class="border-slate-800 my-2" />'; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)/);
    if (ul) {
      if (listType !== 'ul') { closeList(); html += '<ul class="list-disc ml-5 my-1 space-y-0.5">'; listType = 'ul'; }
      html += `<li class="text-[13px] text-slate-300 leading-relaxed">${inline(ul[1])}</li>`; continue;
    }
    const ol = line.match(/^\s*\d+\.\s+(.*)/);
    if (ol) {
      if (listType !== 'ol') { closeList(); html += '<ol class="list-decimal ml-5 my-1 space-y-0.5">'; listType = 'ol'; }
      html += `<li class="text-[13px] text-slate-300 leading-relaxed">${inline(ol[1])}</li>`; continue;
    }
    const quote = line.match(/^\s*>\s?(.*)/);
    if (quote) { closeList(); html += `<div class="border-l-2 border-slate-700 pl-3 my-1 text-[13px] text-slate-400">${inline(quote[1])}</div>`; continue; }
    if (!line.trim()) { closeList(); continue; }
    closeList();
    html += `<p class="text-[13px] text-slate-300 leading-relaxed my-1.5">${inline(line)}</p>`;
  }
  closeList();
  if (inCode) html += '</code></pre>';
  return html;
}

const rendered = computed(() => {
  if (!doc.value || doc.value.error) return '';
  return renderMd(doc.value.content);
});

onMounted(load);
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">
    <!-- 左: 分类 + 列表 -->
    <div class="lg:col-span-2">
      <h1 class="text-xl font-semibold text-slate-100 mb-5">复盘 Knowledge
        <span class="text-[11px] font-normal text-slate-500 ml-2">data/knowledge · 自动生成的分析/复盘/债务</span>
      </h1>

      <div v-if="err" class="card p-3 mb-3 text-red-400 text-[12px]">{{ err }}</div>

      <div class="flex gap-1.5 mb-3 flex-wrap">
        <button v-for="c in cats" :key="c.category" @click="pickCat(c)"
          class="text-[11px] px-2 py-1 rounded border"
          :class="curCat === c.category ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'">
          {{ catLabel[c.category] || c.category }} {{ c.total }}</button>
      </div>

      <div class="space-y-1.5 max-h-[82vh] overflow-y-auto pr-1">
        <div v-for="it in items" :key="it.rel" @click="openDoc(it.rel)"
          class="card p-2.5 cursor-pointer hover:border-slate-600 transition-colors"
          :class="{ 'border-cyan-500/40': doc?.rel === it.rel }">
          <div class="text-[12px] text-slate-300 leading-snug">{{ it.title }}</div>
          <div class="text-[10px] text-slate-600 mt-1 flex gap-2">
            <span v-if="it.created_at">{{ fmtDate(it.created_at) }}</span>
            <span class="truncate">{{ (it.tags || []).join(' · ') }}</span>
          </div>
        </div>
        <div v-if="!items.length" class="card p-4 text-center text-slate-500 text-[12px]">空</div>
        <div v-if="curCatItems?.truncated" class="text-center text-[11px] text-slate-600 pt-1">… 仅显示最近 {{ curCatItems.shown }} / {{ curCatItems.total }} 条</div>
      </div>
    </div>

    <!-- 右: 内容 -->
    <div class="lg:col-span-3">
      <div v-if="loadingContent" class="card p-6 text-center text-slate-500 text-[13px]">加载中…</div>
      <div v-else-if="doc?.error" class="card p-4 text-red-400 text-[13px]">{{ doc.error }}</div>
      <div v-else-if="doc" class="card p-5">
        <div class="flex items-start justify-between gap-3 border-b border-slate-800 pb-3 mb-3">
          <div>
            <div class="text-base font-semibold text-slate-100">{{ doc.meta?.title || doc.rel }}</div>
            <div class="text-[11px] text-slate-500 mt-1.5">
              <span v-if="doc.meta?.created_at">{{ fmtDate(doc.meta.created_at) }}</span>
              <span v-if="doc.meta?.category" class="ml-2">{{ doc.meta.category }}</span>
              <span class="ml-2 mono">{{ doc.rel }}</span>
            </div>
          </div>
          <div v-if="doc.meta?.tags?.length" class="flex flex-wrap gap-1 justify-end shrink-0">
            <span v-for="t in doc.meta.tags" :key="t" class="text-[10px] px-1.5 py-0.5 rounded border border-slate-700 text-slate-500">{{ t }}</span>
          </div>
        </div>
        <!-- md 渲染 -->
        <div class="max-h-[78vh] overflow-y-auto pr-1" v-html="rendered"></div>
      </div>
      <div v-else class="card p-6 text-center text-slate-500 text-[13px]">选择左侧一篇文档</div>
    </div>
  </div>
</template>
