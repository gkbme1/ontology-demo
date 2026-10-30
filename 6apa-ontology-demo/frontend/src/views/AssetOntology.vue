<script setup lang="ts">
/**
 * 资产本体：左侧资产导航树，右侧所选对象的本体档案（属性 / 关系 / 能力 / 约束 / 规则）。
 * 地址栏 ?id= 记录当前对象，可直接分享或刷新后恢复；从档案里点关联对象会同步展开左侧树。
 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { AssetProfile as Profile } from '@/api/types'
import AssetTree from '@/components/AssetTree.vue'
import AssetProfile from '@/components/AssetProfile.vue'

const route = useRoute()
const router = useRouter()
const tree = ref<InstanceType<typeof AssetTree> | null>(null)
const profile = ref<Profile | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

let seq = 0
async function open(objectId: string, syncTree: boolean) {
  const mine = ++seq
  loading.value = true
  error.value = null
  try {
    const p = await api.assetProfile(objectId)
    if (mine !== seq) return
    profile.value = p
    if (syncTree && p.treePath.length) await tree.value?.expandPath(p.treePath)
    if (route.query.id !== p.objectId) router.replace({ query: { ...route.query, id: p.objectId } })
  } catch (e) {
    if (mine === seq) error.value = (e as Error).message
  } finally {
    if (mine === seq) loading.value = false
  }
}

function onTreeSelect(objectId: string) {
  void open(objectId, false)
}

watch(() => route.query.id, (id) => {
  if (typeof id === 'string' && id && id !== profile.value?.objectId) void open(id, true)
})

onMounted(() => {
  const id = route.query.id
  if (typeof id === 'string' && id) void open(id, true)
})
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-[340px_minmax(0,1fr)] h-[calc(100vh-54px)]">
    <aside class="border-r border-line bg-ink-panel min-h-0 flex flex-col">
      <div class="px-4 pt-3 text-fg-mute text-[10.5px] tracking-widest uppercase">资产导航</div>
      <div class="flex-1 min-h-0">
        <AssetTree ref="tree" :selected-object-id="profile?.objectId" @select="onTreeSelect" />
      </div>
    </aside>

    <main class="min-w-0 min-h-0 overflow-y-auto px-5 pt-4 pb-12">
      <div v-if="error" class="mb-4 px-3 py-2.5 border-l-2 border-err bg-err/[0.07] text-fg-dim">{{ error }}</div>
      <div v-if="loading && !profile" class="empty">加载中…</div>
      <div :class="{ 'opacity-60 transition-opacity': loading && profile }">
        <AssetProfile v-if="profile" :profile="profile" @open="(id) => open(id, true)" />
      </div>
      <div v-if="!profile && !loading && !error" class="panel">
        <div class="panel-body text-[13px] text-fg-dim leading-relaxed space-y-2">
          <div class="text-fg text-[15px] font-semibold">从左侧资产树找到对象</div>
          <p class="m-0">树按本体域分类：<b class="text-fg">工业资产</b>按 大类 → 设备类型 → 标准设备组 → 设备 逐级展开；
            <b class="text-fg">空间与布局</b>按工段列出；<b class="text-fg">工艺</b>、<b class="text-fg">物料</b>、<b class="text-fg">控制</b>、<b class="text-fg">质量</b>、<b class="text-fg">安全</b>等域列出本体中的对应对象。</p>
          <p class="m-0">也可以在上方搜索框直接输入设备名、DCS 位号或工段编号。选中后右侧显示该对象的本体：属性（含数据关联）、关系、能力、约束与适用规则。</p>
        </div>
      </div>
    </main>
  </div>
</template>
