<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type GroupView } from '../api/client'
import { loadSession } from '../composables/session'
import { t } from '../i18n'
import StatusDistBar from '../components/StatusDistBar.vue'

// 结果列表 · 第一级（P15 三级导航，对齐竞品「我的查询」）：
// 查询组卡片（状态分布条 + 单号/批次计数）→ 点入组内批次 → 批次内单号。
// 组管理（新建/重命名/删除）合并进本页，替代原「组与批次」页。
const route = useRoute()
const router = useRouter()

const groups = ref<GroupView[]>([])
const loading = ref(true)
const error = ref('')

// 管理
const createOpen = ref(false)
const newName = ref('')
const busy = ref(false)
const renameTarget = ref<GroupView | null>(null)
const renameName = ref('')
const deleteTarget = ref<GroupView | null>(null)

onMounted(async () => {
  // 旧深链兼容：/results?op= → 批次页；/results?group= → 组页
  const qOp = route.query.op
  if (typeof qOp === 'string' && qOp) {
    await router.replace(`/results/batch/${qOp}`)
    return
  }
  const qGroup = route.query.group
  if (typeof qGroup === 'string' && qGroup) {
    await router.replace(`/results/group/${qGroup}`)
    return
  }
  await loadSession(true)
  await reload()
})

async function reload() {
  loading.value = groups.value.length === 0
  error.value = ''
  try {
    const { data } = await api.get<GroupView[]>('/api/v1/groups')
    groups.value = data
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    loading.value = false
  }
}

function fmtDate(s?: string): string {
  if (!s) return ''
  const d = new Date(s)
  return t('results.created_at', { date: `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}` })
}

async function createGroup() {
  if (!newName.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.post<GroupView>('/api/v1/groups', { name: newName.value.trim() })
    createOpen.value = false
    newName.value = ''
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

function openRename(g: GroupView) {
  renameTarget.value = g
  renameName.value = g.name
}

async function doRename() {
  if (!renameTarget.value || !renameName.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.patch<GroupView>(`/api/v1/groups/${renameTarget.value.id}`, {
      name: renameName.value.trim(),
    })
    renameTarget.value = null
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}

function openDelete(g: GroupView) {
  deleteTarget.value = g
}

async function doDelete() {
  if (!deleteTarget.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await api.del(`/api/v1/groups/${deleteTarget.value.id}`)
    deleteTarget.value = null
    await reload()
  } catch (e) {
    error.value = (e as { message: string }).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section>
    <div class="title-row">
      <div>
        <h1 class="page-title">{{ t('results.title') }}</h1>
        <p class="page-sub">{{ t('results.sub') }}</p>
      </div>
      <button class="btn" @click="createOpen = true">{{ t('results.new_group') }}</button>
    </div>

    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <p v-if="loading" class="hint" role="status">{{ t('common.loading') }}</p>

    <div v-else-if="groups.length === 0" class="card empty-state" role="status">
      <p>{{ t('results.group_empty') }}</p>
      <RouterLink class="btn" to="/submit">{{ t('results.empty_cta') }}</RouterLink>
    </div>

    <div v-else class="groups">
      <div
        v-for="g in groups"
        :key="g.id"
        class="card gcard"
        role="link" tabindex="0"
        @click="router.push(`/results/group/${g.id}`)"
        @keydown.enter.prevent="router.push(`/results/group/${g.id}`)"
      >
        <div class="gcard-head">
          <span class="g-name">{{ g.name }}</span>
          <span v-if="g.is_default" class="badge">{{ t('results.default_badge') }}</span>
          <span v-if="g.archived" class="badge warn">{{ t('results.archived_badge') }}</span>
          <span class="meta">{{ t('results.group_meta', { t: g.tracking_count, b: g.batch_count }) }}</span>
          <span class="spacer"></span>
          <button
            class="linklike act" role="button"
            @click.stop="openRename(g)"
          >{{ t('results.rename') }}</button>
          <button
            class="linklike act danger" role="button"
            @click.stop="openDelete(g)"
          >{{ t('results.delete') }}</button>
        </div>
        <StatusDistBar :distribution="g.status_distribution" :total="g.tracking_count" />
        <div class="gcard-foot">
          <span class="hint">{{ fmtDate(g.created_at) }}</span>
          <span class="hint enter">{{ t('results.view_batches') }}</span>
        </div>
      </div>
    </div>

    <!-- 新建组 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal card" role="dialog" aria-modal="true" :aria-label="t('results.create_title')">
        <h3>{{ t('results.create_title') }}</h3>
        <input v-model="newName" :placeholder="t('results.name_placeholder')" maxlength="50" @keydown.enter.prevent="createGroup" />
        <div class="actions">
          <button class="btn" :disabled="!newName.trim() || busy" @click="createGroup">{{ t('results.create_btn') }}</button>
          <button class="btn ghost" @click="createOpen = false">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>

    <!-- 重命名 -->
    <div v-if="renameTarget" class="modal-mask" @click.self="renameTarget = null">
      <div class="modal card" role="dialog" aria-modal="true" :aria-label="t('results.rename')">
        <h3>{{ t('results.rename_title', { name: renameTarget.name }) }}</h3>
        <input v-model="renameName" maxlength="50" @keydown.enter.prevent="doRename" />
        <div class="actions">
          <button class="btn" :disabled="!renameName.trim() || busy" @click="doRename">{{ t('results.save') }}</button>
          <button class="btn ghost" @click="renameTarget = null">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>

    <!-- 删除确认（危险操作语义：只清组织关系，事实与账务保留） -->
    <div v-if="deleteTarget" class="modal-mask" @click.self="deleteTarget = null">
      <div class="modal card" role="dialog" aria-modal="true" :aria-label="t('results.delete')">
        <h3>{{ t('results.delete_title', { name: deleteTarget.name }) }}</h3>
        <p class="hint">
          {{ t('results.delete_hint', { n: deleteTarget.tracking_count }) }}
        </p>
        <div class="actions">
          <button class="btn danger" :disabled="busy" @click="doDelete">{{ t('results.delete_confirm') }}</button>
          <button class="btn ghost" @click="deleteTarget = null">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.title-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.groups { display: flex; flex-direction: column; gap: 12px; margin-top: 8px; }
.gcard { cursor: pointer; transition: box-shadow var(--dur) ease-out, border-color var(--dur) ease-out; }
.gcard:hover { box-shadow: var(--shadow-1); border-color: var(--brand-line); }
.gcard-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.g-name { font-weight: 700; font-size: 16px; }
.meta { color: var(--fg-soft); font-size: 13px; }
.spacer { flex: 1; }
.linklike { background: none; border: 0; padding: 2px 8px; cursor: pointer; font-size: 13px; color: var(--fg-soft); border-radius: 6px; }
.linklike:hover { color: var(--brand); background: var(--brand-soft); }
.linklike.danger:hover { color: var(--err); background: var(--err-soft); }
.gcard-foot { display: flex; justify-content: space-between; margin-top: 8px; }
.enter { color: var(--brand); font-weight: 500; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(28, 25, 23, 0.4);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal { width: min(440px, 92vw); margin: 0; box-shadow: var(--shadow-2); }
.actions { display: flex; gap: 12px; margin-top: 12px; }
</style>
