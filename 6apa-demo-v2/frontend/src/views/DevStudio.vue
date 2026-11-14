<script setup lang="ts">
/**
 * 开发态（需求 4.2，图 4-3(a)、4-4～4-17）：左侧功能模块——元模型、层级类型、类库、关系类型、能力与算法（映射规则先屏蔽，页面 dev/MappingRulesPage.vue 保留）、类库版本。
 * 类库可编辑；当前版本「编辑中」时可改，发布后只读（修改须基于已发布版本新建版本）。开发态修改同步到工程态不做。
 */
import { onMounted } from 'vue'
import { lib, reloadLib } from '@/composables/useClassLib'
import MetaModelPage from './dev/MetaModelPage.vue'
import HierarchyPage from './dev/HierarchyPage.vue'
import ClassLibPage from './dev/ClassLibPage.vue'
import RelationTypesPage from './dev/RelationTypesPage.vue'
import CapAlgoPage from './dev/CapAlgoPage.vue'
import VersionsPage from './dev/VersionsPage.vue'

const PAGES = [['meta', '元模型'], ['hier', '层级类型'], ['class', '类库'], ['rel', '关系类型'], ['cap', '能力与算法'], ['ver', '类库版本']] as const
onMounted(() => { if (!lib.summary) reloadLib() })
</script>

<template>
  <div class="h-full grid grid-cols-[180px_1fr] min-h-0">
    <aside class="border-r border-line bg-ink-panel py-3">
      <div class="px-4 pb-2 text-xs text-fg-mute">开发态</div>
      <button v-for="[k, l] in PAGES" :key="k" class="w-full text-left px-4 py-2.5 text-[14px] border-l-[3px]"
              :class="lib.page === k ? 'bg-brand/10 border-brand text-brand font-semibold' : 'border-transparent text-fg-dim hover:bg-ink-panel2'"
              @click="lib.page = k">{{ l }}</button>
    </aside>
    <main class="min-h-0 overflow-auto bg-ink px-5 py-4">
      <div v-if="lib.error" class="empty mb-3">{{ lib.error }}</div>
      <div v-if="lib.msg" class="fixed right-6 top-16 z-50 rounded-md bg-fg text-white text-xs px-3 py-2 shadow-lg">{{ lib.msg }}</div>
      <div v-if="lib.summary && lib.summary.current.status !== '编辑中'" class="mb-3 rounded-md border border-warn/40 bg-warn/5 px-3 py-2 text-xs text-warn">
        类库 {{ lib.summary.current.version }} 已发布，只读；要修改请到「类库版本」基于它新建版本。
      </div>
      <MetaModelPage v-if="lib.page === 'meta'" />
      <HierarchyPage v-else-if="lib.page === 'hier'" />
      <ClassLibPage v-else-if="lib.page === 'class'" />
      <RelationTypesPage v-else-if="lib.page === 'rel'" />
      <CapAlgoPage v-else-if="lib.page === 'cap'" />
      <VersionsPage v-else-if="lib.page === 'ver'" />
    </main>
  </div>
</template>
