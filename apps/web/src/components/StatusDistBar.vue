<script setup lang="ts">
import { computed } from 'vue'

// 物流状态分布条（P15，对齐竞品）：按固定顺序的分段水平条 + 图例计数。
const props = defineProps<{
  distribution: Record<string, number>
  total: number
  compact?: boolean
}>()

/* 分段顺序与配色：brand 系中性过渡 + 语义色，只用既有 token。 */
const ORDER: { key: string; label: string; color: string }[] = [
  { key: 'delivered', label: '已签收', color: 'var(--ok)' },
  { key: 'out_for_delivery', label: '派送中', color: '#0d9488' },
  { key: 'in_transit', label: '运输中', color: 'var(--brand)' },
  { key: 'available_for_pickup', label: '到达待取', color: '#14b8a6' },
  { key: 'accepted', label: '已揽收', color: '#0e7490' },
  { key: 'label_created', label: '已下单', color: '#64748b' },
  { key: 'not_found', label: '未找到', color: '#a8a29e' },
  { key: 'exception', label: '异常', color: 'var(--warn)' },
  { key: 'postage_due', label: '邮资未付', color: '#d97706' },
  { key: 'delivery_attempted', label: '投递失败', color: 'var(--err)' },
  { key: 'returned', label: '退回', color: 'var(--orange)' },
  { key: 'other', label: '其他', color: '#d6d3d1' },
]

const segments = computed(() => {
  if (props.total <= 0) return []
  return ORDER
    .map((s) => ({ ...s, n: props.distribution[s.key] ?? 0 }))
    .filter((s) => s.n > 0)
    .map((s) => ({ ...s, pct: (s.n / props.total) * 100 }))
})
</script>

<template>
  <div class="dist" :class="{ compact }">
    <div class="bar" role="img" :aria-label="`状态分布：共 ${total} 条`">
      <span
        v-for="s in segments"
        :key="s.key"
        class="seg"
        :style="{ width: s.pct + '%', background: s.color }"
        :title="`${s.label} ${s.n}`"
      ></span>
    </div>
    <div class="legend">
      <span v-for="s in segments" :key="s.key" class="lg">
        <span class="dot" :style="{ background: s.color }" aria-hidden="true"></span>
        {{ s.label }} <strong>{{ s.n }}</strong>
      </span>
      <span v-if="total === 0" class="lg dim">暂无状态数据</span>
    </div>
  </div>
</template>

<style scoped>
.dist { margin: 8px 0; }
.bar {
  display: flex; height: 10px; border-radius: 999px; overflow: hidden;
  background: var(--bg);
}
.seg { min-width: 2px; transition: width 300ms ease-out; }
.legend {
  display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 6px;
  font-size: 12.5px; color: var(--fg-soft);
}
.lg { display: inline-flex; align-items: center; gap: 5px; }
.lg strong { color: var(--fg); font-weight: 600; }
.lg.dim { font-style: italic; }
.dot { width: 8px; height: 8px; border-radius: 999px; flex: none; }
.dist.compact .legend { gap: 2px 10px; }
</style>
