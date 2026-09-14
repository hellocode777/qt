<script setup>
import { onMounted, ref, computed } from 'vue';
import { api, fmtMoney, fmtPct, pnlClass } from '../api';
const positions = ref([]);
const quoteDate = ref('');
const fees = ref(null);
const err = ref('');
const filter = ref('active'); // active | all

const shown = computed(() =>
  filter.value === 'active' ? positions.value.filter(p => p.is_active) : positions.value
);

// 活跃行 = 最新收盘标记值；历史行 = 记录时点值（已实现，平仓结算）
const mktValue = p => (p.is_active && p.market_value_latest != null) ? p.market_value_latest : p.market_value;
const priceCol = p => p.is_active ? p.latest_price : (p.exit_price || null);
const pnlValue = p => p.is_active ? p.unrealized_pnl : p.pnl;
const pnlPctPct = p => {
  const v = p.is_active ? p.unrealized_pnl_pct : p.pnl_pct; // 后端口径为小数
  return (v === null || v === undefined) ? null : v * 100;
};
// 费用后（估算）：后端 PositionService 计算，未计券商最低佣金/过户费
const netValue = p => p.is_active ? p.unrealized_pnl_net : p.realized_pnl_net;
const netPctPct = p => {
  const v = p.is_active ? p.unrealized_pnl_net_pct : p.realized_pnl_net_pct;
  return (v === null || v === undefined) ? null : v * 100;
};
const feeTip = p => {
  if (p.est_buy_fee == null) return '费用估算不可用（无成本价）';
  const sell = p.est_sell_fee;
  return `费用估算: 买入 ¥${p.est_buy_fee}` + (sell == null ? '' : ` + 卖出 ¥${sell} = ¥${p.est_round_trip_fee}`)
    + '；佣金0.025%双向 + 印花税0.05%(卖) + 滑点0.1%双向（未含券商最低佣金/过户费）';
};

async function load() {
  try {
    const d = await api.positions();
    positions.value = d.positions;
    quoteDate.value = d.quote_date || '';
    fees.value = d.meta?.fees || null;
  } catch (e) { err.value = e.message; }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-5">
      <h1 class="text-xl font-semibold text-slate-100">持仓 <span class="text-[11px] font-normal text-slate-500 ml-2">positions.parquet · {{ positions.length }} 条 · 活跃行市值/盈亏按 {{ quoteDate || '—' }} 收盘标记 · 历史行 = 已实现盈亏</span></h1>
      <div class="flex gap-2">
        <button @click="filter='active'" class="text-[12px] px-3 py-1.5 rounded-md border"
          :class="filter==='active' ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'">活跃</button>
        <button @click="filter='all'" class="text-[12px] px-3 py-1.5 rounded-md border"
          :class="filter==='all' ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'">全部历史</button>
      </div>
    </div>

    <div v-if="err" class="card p-3 mb-4 text-red-400 text-[13px]">{{ err }}</div>

    <div class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-[13px]">
          <thead>
            <tr class="text-left text-slate-500 text-[11px] border-b border-slate-800 bg-slate-900/60">
              <th class="px-4 py-2">#</th><th class="px-4 py-2">代码</th><th class="px-4 py-2">策略</th><th class="px-4 py-2">状态</th>
              <th class="px-4 py-2 text-right">建仓</th><th class="px-4 py-2 text-right">成本价</th>
              <th class="px-4 py-2 text-right">最新价 / 平仓价</th><th class="px-4 py-2 text-right">股数</th>
              <th class="px-4 py-2 text-right">市值</th><th class="px-4 py-2 text-right">盈亏</th><th class="px-4 py-2 text-right">盈亏%</th>
              <th class="px-4 py-2 text-right">净盈亏(费后)</th>
              <th class="px-4 py-2">平仓原因 / 备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in shown" :key="p.position_id" class="border-b border-slate-800/50 hover:bg-slate-800/30"
              :class="{ 'opacity-50': !p.is_active }">
              <td class="px-4 py-2 text-slate-600 mono">{{ p.position_id }}</td>
              <td class="px-4 py-2"><RouterLink :to="`/chart?code=${p.symbol}`"
                class="mono text-slate-100 hover:text-cyan-300 hover:underline underline-offset-2">{{ p.symbol }}</RouterLink></td>
              <td class="px-4 py-2 text-slate-400">{{ p.strategy_id }}</td>
              <td class="px-4 py-2">
                <span class="text-[10px] px-1.5 py-0.5 rounded"
                  :class="p.is_active ? 'bg-cyan-500/15 text-cyan-300 border border-cyan-500/20' : 'bg-slate-700/40 text-slate-400'">
                  {{ p.is_active ? 'ACTIVE' : p.status_name || p.status }}</span>
              </td>
              <td class="px-4 py-2 mono text-right text-slate-400">{{ p.entry_date }}</td>
              <td class="px-4 py-2 mono text-right">{{ p.entry_price }}</td>
              <td class="px-4 py-2 mono text-right text-slate-400"
                :title="p.is_active ? `最新收盘 ${p.quote_date || '—'}${p.latest_suspended ? ' (停牌)' : ''}` : '平仓价'">
                {{ fmtMoney(priceCol(p)) }}</td>
              <td class="px-4 py-2 mono text-right">{{ p.shares }}</td>
              <td class="px-4 py-2 mono text-right">{{ fmtMoney(mktValue(p)) }}</td>
              <td class="px-4 py-2 mono text-right" :class="pnlClass(pnlValue(p))">{{ fmtMoney(pnlValue(p)) }}</td>
              <td class="px-4 py-2 mono text-right" :class="pnlClass(pnlPctPct(p))">{{ fmtPct(pnlPctPct(p)) }}</td>
              <td class="px-4 py-2 mono text-right" :class="pnlClass(netValue(p))" :title="feeTip(p)">
                {{ fmtMoney(netValue(p)) }}
                <span class="text-[11px] text-slate-500">{{ fmtPct(netPctPct(p)) }}</span>
              </td>
              <td class="px-4 py-2 text-slate-500 max-w-56 truncate" :title="p.notes">{{ p.exit_reason || p.notes || '—' }}</td>
            </tr>
            <tr v-if="!shown.length"><td colspan="13" class="px-4 py-6 text-center text-slate-500">无数据</td></tr>
          </tbody>
        </table>
      </div>
      <div class="px-4 py-2 text-[10px] text-slate-600 border-t border-slate-800">
        活跃行：市值/盈亏 = 最新收盘价 × 股数（毛）；净盈亏 = 毛盈亏 − 买入费 − 卖出费（估算）。
        历史行：盈亏/盈亏% = 平仓时已实现；净盈亏 = 已实现 − 估算费用。
        <template v-if="fees">费率：佣金 {{ (fees.commission_rate * 100).toFixed(3) }}% 双向 · 印花税 {{ (fees.stamp_tax_rate * 100).toFixed(3) }}% 卖出 · 滑点 {{ (fees.slippage_bps / 100).toFixed(2) }}% 双向 · 来源 {{ fees.source }}；未含{{ fees.excludes }}。无行情或停牌显示 —。费用按“每行都真实成交”估算：若某行是记账回滚（entry=exit、pnl=0，如 rollback_* 原因），实际未成交，其费用属记账假象。</template>
      </div>
    </div>
  </div>
</template>
