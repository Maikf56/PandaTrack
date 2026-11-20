<script setup lang="ts">
import { computed } from 'vue'
import { t } from '../i18n'

// 物流状态分布条（P15，对齐竞品）：按固定顺序的分段水平条 + 图例计数。
const props = defineProps<{
  distribution: Record<string, number>
  total: number
  compact?: boolean
}>()

/* 分段顺序与配色：brand 系中性过渡 + 语义色，只用既有 token。
   label 走 i18n（status.* 词典），key 为稳定标识。 */
const ORDER: { key: string; color: string }[] = [
  { key: 'delivered', color: 'var(--ok)' },
  { key: 'out_for_delivery', color: '#0d9488' },
  { key: 'in_transit', color: 'var(--brand)' },
  { key: 'available_for_pickup', color: '#14b8a6' },
  { key: 'accepted', color: '#0e7490' },
  { key: 'label_created', color: '#64748b' },
  { key: 'not_found', color: '#a8a29e' },
  { key: 'exception', color: 'var(--warn)' },
  { key: 'postage_due', color: '#d97706' },
  { key: 'delivery_attempted', color: 'var(--err)' },
  { key: 'returned', color: 'var(--orange)' },
  { key: 'other', color: '#d6d3d1' },
]

const segments = computed(() => {
  if (props.total <= 0) return []
  return ORDER
    .map((s) => ({ ...s, label: t(`status.${s.key}`), n: props.distribution[s.key] ?? 0 }))
    .filter((s) => s.n > 0)
    .map((s) => ({ ...s, pct: (s.n / props.total) * 100 }))
})

const aria = computed(() => t('dist.aria', { n: props.total }))
</script>

<template>
  <div class="dist" :class="{ compact }">
    <div class="bar" role="img" :aria-label="aria">
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
      <span v-if="total === 0" class="lg dim">{{ t('dist.empty') }}</span>
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
