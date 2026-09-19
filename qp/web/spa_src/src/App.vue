<script setup>
import { useRoute } from 'vue-router';

const route = useRoute();
const nav = [
  { to: '/', icon: '◧', label: '总览' },
  { to: '/experiments', icon: '↺', label: '回测' },
  { to: '/simulation', icon: '◨', label: '影子' },
  { to: '/paper', icon: '◔', label: '模拟盘' },
  { to: '/positions', icon: '▤', label: '持仓' },
  { to: '/chart', icon: '◫', label: '行情' },
  { to: '/strategies', icon: '◈', label: '策略' },
  { to: '/factors', icon: '✦', label: '因子' },
  { to: '/industry', icon: '◭', label: '行业' },
  { to: '/monitor', icon: '♡', label: '监控' },
  { to: '/decisions', icon: '◉', label: '决策' },
  { to: '/knowledge', icon: '⟳', label: '复盘' },
];
</script>

<template>
  <div class="flex h-full">
    <!-- 左侧导航 -->
    <aside class="w-44 shrink-0 bg-[#0d1220] border-r border-slate-800 flex flex-col">
      <div class="px-4 py-4 border-b border-slate-800">
        <div class="text-lg font-bold tracking-wide text-slate-100">QP <span class="text-cyan-400">Terminal</span></div>
        <div class="text-[10px] text-slate-500 mt-0.5">原型 prototype · 数据=qp真实产物</div>
      </div>
      <nav class="flex-1 py-3 overflow-y-auto">
        <RouterLink v-for="n in nav" :key="n.to" :to="n.to"
          class="flex items-center gap-2.5 px-4 py-2.5 mx-2 my-0.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-slate-800/60 transition-colors"
          :class="{ '!text-cyan-300 !bg-cyan-500/10 border border-cyan-500/20': route.path === n.to }">
          <span class="text-sm">{{ n.icon }}</span>
          <span class="text-[13px]">{{ n.label }}</span>
        </RouterLink>
      </nav>
      <div class="px-4 py-3 border-t border-slate-800 text-[10px] text-slate-600 leading-relaxed">
        freqUI 思路 × qp 数据<br />
        ECharts · Vue3 · Tailwind
      </div>
    </aside>

    <!-- 主区 -->
    <main class="flex-1 overflow-y-auto p-5">
      <div class="max-w-6xl mx-auto">
        <RouterView />
      </div>
    </main>
  </div>
</template>
