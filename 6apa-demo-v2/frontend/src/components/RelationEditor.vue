<script setup lang="ts">
/**
 * 在对象详情中新增关系（需求 SW-044 拓扑关系、SW-049 工艺影响关系）：本对象作为起点或终点，
 * 对端从候选中搜索选择（名称 / 拼音首字母），后端按关系类型校验端点类型；保存后全局图谱同步更新。
 */
import { computed, ref, watch } from 'vue'
import { api } from '@/api/client'
import Modal from './Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ mode: 'topology' | 'influence'; self: { id: string; name: string }; params?: { id: string; name: string }[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved'): void }>()

const TYPES = props.mode === 'topology' ? ['物理拓扑', '工艺流向', '供应'] : ['工艺影响']
const HINT: Record<string, string> = {
  物理拓扑: '设备 / 设备组之间的管线连接（起点 → 下游）', 工艺流向: '物料流入 / 流出设备', 供应: '公用介质供给设备 / 设备组',
  工艺影响: '本对象的工艺参数影响另一个参数或质量指标'
}
const type = ref(TYPES[0])
const selfIs = ref<'from' | 'to'>('from')
const selfParam = ref(props.params?.[0]?.id ?? '')
const kw = ref('')
const cands = ref<Any[]>([])
const allowed = ref<string[]>([])
const other = ref<Any>(null)
const label = ref('正向影响')
const mechanism = ref('')
const lag = ref('')
const error = ref('')

// 供应的起点只能是公用介质：本对象（设备 / 设备组）只能作终点
watch(type, (t) => { if (t === '供应') selfIs.value = 'to'; other.value = null; load() })
watch(selfIs, () => { other.value = null; load() })
let timer: number | undefined
watch(kw, () => { window.clearTimeout(timer); timer = window.setTimeout(load, 200) })
async function load(): Promise<void> {
  try {
    const r = await api.relationCandidates({ type: type.value, end: selfIs.value === 'from' ? 'to' : 'from', keyword: kw.value })
    cands.value = r.items.filter((x: Any) => x.id !== props.self.id)
    allowed.value = r.allowed
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
load()
const selfEnd = computed(() => (props.mode === 'influence' ? { id: selfParam.value } : { id: props.self.id }))
async function save(): Promise<void> {
  error.value = ''
  if (!other.value) { error.value = '请选择对端对象'; return }
  const me = selfEnd.value
  const you = { id: other.value.id }
  try {
    await api.createRelation({ type: type.value, from: selfIs.value === 'from' ? me : you, to: selfIs.value === 'from' ? you : me,
                               label: type.value === '工艺影响' ? label.value : undefined, mechanism: mechanism.value, lag: lag.value })
    emit('saved')
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="mode === 'topology' ? `新增拓扑关系 · ${self.name}` : `新增工艺影响关系 · ${self.name}`" @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存</button></template>
    <div class="space-y-3 text-sm">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-fg-mute text-xs w-16">关系类型</span>
        <button v-for="t in TYPES" :key="t" class="ctl" :class="{ 'ctl-on': type === t }" @click="type = t">{{ t }}</button>
        <span class="text-[11px] text-fg-mute">{{ HINT[type] }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-fg-mute text-xs w-16">本对象是</span>
        <button class="ctl" :class="{ 'ctl-on': selfIs === 'from' }" :disabled="type === '供应'" @click="selfIs = 'from'">起点（影响 / 上游）</button>
        <button class="ctl" :class="{ 'ctl-on': selfIs === 'to' }" @click="selfIs = 'to'">终点（被影响 / 下游）</button>
      </div>
      <div v-if="mode === 'influence'" class="flex items-center gap-2">
        <span class="text-fg-mute text-xs w-16">本对象参数</span>
        <select v-model="selfParam" class="inp w-60"><option v-for="p in params" :key="p.id" :value="p.id">{{ p.name }}</option></select>
        <span class="text-fg-mute text-xs">方向</span>
        <select v-model="label" class="inp w-28"><option>正向影响</option><option>负向影响</option><option>影响</option></select>
      </div>
      <div>
        <div class="flex items-center gap-2">
          <span class="text-fg-mute text-xs w-16">对端对象</span>
          <input v-model="kw" class="inp w-60" placeholder="名称 / 拼音首字母" />
          <span class="text-[11px] text-fg-mute">可选：{{ allowed.join('、') }}</span>
        </div>
        <div class="mt-1 ml-[72px] max-h-48 overflow-auto border border-line-soft rounded">
          <div v-for="c in cands" :key="c.id" class="tree-row !py-1" :class="{ '!bg-brand/15': other?.id === c.id }" @click="other = c">
            <span class="pill pill-plain">{{ c.kindName }}</span><span class="flex-1 truncate">{{ c.name }}</span>
            <span class="text-[11px] text-fg-mute truncate max-w-[180px]">{{ c.hint }}</span>
          </div>
          <div v-if="!cands.length" class="px-2 py-1.5 text-xs text-fg-mute">没有匹配的对象</div>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-fg-mute text-xs w-16">机理说明</span>
        <input v-model="mechanism" class="inp flex-1" placeholder="如：夹套热水给水解罐加热" />
        <template v-if="mode === 'influence'">
          <span class="text-fg-mute text-xs">典型时滞</span><input v-model="lag" class="inp w-24" placeholder="如 10 分钟" />
        </template>
      </div>
      <div class="text-xs text-fg-dim" v-if="other">
        将新增：<b>{{ selfIs === 'from' ? (mode === 'influence' ? params?.find((p) => p.id === selfParam)?.name : self.name) : other.name }}</b>
        —{{ type === '工艺影响' ? label : type }}→
        <b>{{ selfIs === 'from' ? other.name : (mode === 'influence' ? params?.find((p) => p.id === selfParam)?.name : self.name) }}</b>（状态：草案·待工艺确认）
      </div>
      <div v-if="error" class="text-err text-xs">{{ error }}</div>
    </div>
  </Modal>
</template>
