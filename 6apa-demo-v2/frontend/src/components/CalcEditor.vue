<script setup lang="ts">
/**
 * 新建 / 编辑计算组态（需求 ONTO-SR-SW-050）：作用范围 + 引用算法 + 参数绑定 + 执行设置（周期 / 事件触发 / 按需、周期、超时、失败处理）
 * + 输出（XBase 计算测点）。保存时后端校验绑定完整、类型匹配、引用存在。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import Modal from './Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ calc?: Any; anchorOptions: { id: string; name: string; kind: string }[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', c: Any): void }>()

const algos = ref<Any[]>([])
const meta = ref<Any>(null)
const allCalcs = ref<Any[]>([])
const params = ref<Any[]>([])
const error = ref('')
const c0 = props.calc
const form = ref<Any>({
  name: c0?.name ?? '', anchorId: c0?.anchor?.id ?? props.anchorOptions[0]?.id ?? '', algorithmId: c0?.algorithmId ?? '',
  bindings: JSON.parse(JSON.stringify(c0?.bindings ?? {})), unit: c0?.unit ?? '', description: c0?.description ?? '', basis: c0?.basis ?? '',
  status: c0?.status ?? '草案·待工艺确认',
  execution: { mode: '按需', periodSec: 60, trigger: '', timeoutSec: 30, onFailure: '跳过', retries: 0, disableAfter: 3, ...(c0?.execution ?? {}) },
  output: { tag: '', writeBack: false, ...(c0?.output ?? {}) }
})
onMounted(async () => {
  const [a, m, cs] = await Promise.all([api.algorithms(), api.calcMeta(), api.calculations()])
  algos.value = a.items
  meta.value = m
  allCalcs.value = cs.items.filter((x: Any) => x.id !== c0?.id)
  if (!form.value.algorithmId && algos.value.length) form.value.algorithmId = algos.value[0].id
})
const algo = computed(() => algos.value.find((a) => a.id === form.value.algorithmId))
const anchor = computed(() => props.anchorOptions.find((a) => a.id === form.value.anchorId))
watch(() => form.value.anchorId, async (id) => {
  params.value = id && (id.startsWith('equip-') || id.startsWith('egrp-')) ? (await api.objectParameters(id)).items : []
}, { immediate: true })
// 换算法时按输入定义预置绑定：常量取默认值，其余绑本对象参数
watch(algo, (a) => {
  if (!a) return
  const b: Any = {}
  for (const inp of a.inputs) {
    const old = form.value.bindings[inp.name]
    if (old) b[inp.name] = old
    else if (inp.type === '常量') { if (inp.default !== undefined && inp.default !== null) b[inp.name] = { kind: 'const', value: inp.default } }
    else b[inp.name] = { kind: 'parameter', name: '' }
  }
  form.value.bindings = b
  if (!form.value.unit) form.value.unit = a.output?.unit ?? ''
})
function setKind(name: string, kind: string): void {
  form.value.bindings[name] = kind === 'const' ? { kind, value: 0 } : kind === 'groupParameter'
    ? { kind, groupId: anchor.value?.kind === 'group' ? anchor.value.id : '', name: '' } : kind === 'tag' ? { kind, tag: '' }
    : kind === 'calc' ? { kind, calcId: '' } : { kind, name: '' }
}
async function save(): Promise<void> {
  error.value = ''
  const f = form.value
  const body = { ...f, anchor: { kind: anchor.value?.kind, id: anchor.value?.id, name: anchor.value?.name } }
  delete body.anchorId
  for (const [k, v] of Object.entries(body.bindings) as [string, Any][]) {
    if (v.kind === 'parameter' && (v.index === '' || v.index === null || v.index === undefined)) delete v.index
    if (v.kind === 'parameter' && v.index !== undefined) v.index = Number(v.index)
    if (v.kind === 'const') v.value = Number(v.value)
    if (!v.kind) delete body.bindings[k]
  }
  try {
    const saved = c0 ? await api.updateCalc(c0.id, body) : await api.createCalc(body)
    emit('saved', saved)
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
</script>

<template>
  <Modal :title="calc ? `编辑计算组态 · ${calc.id}` : '新建计算组态'" wide @close="emit('close')">
    <template #actions><button class="btn btn-primary" @click="save">保存</button></template>
    <div class="space-y-3 text-sm">
      <div class="grid grid-cols-[90px_1fr_90px_1fr] gap-x-3 gap-y-2 items-center">
        <span class="text-xs text-fg-mute">名称</span><input v-model="form.name" class="inp" />
        <span class="text-xs text-fg-mute">作用范围</span>
        <select v-model="form.anchorId" class="inp"><option v-for="a in anchorOptions" :key="a.id" :value="a.id">[{{ a.kind === 'group' ? '设备组' : a.kind === 'segment' ? '工艺段' : '设备' }}] {{ a.name }}</option></select>
        <span class="text-xs text-fg-mute">引用算法</span>
        <select v-model="form.algorithmId" class="inp"><option v-for="a in algos" :key="a.id" :value="a.id">{{ a.name }}（{{ a.id }} v{{ a.version }}）</option></select>
        <span class="text-xs text-fg-mute">输出单位</span><input v-model="form.unit" class="inp" />
        <span class="text-xs text-fg-mute">说明</span><input v-model="form.description" class="inp" />
        <span class="text-xs text-fg-mute">依据</span><input v-model="form.basis" class="inp" />
      </div>
      <div v-if="algo" class="text-[11px] text-fg-mute">{{ algo.description }}</div>

      <div>
        <div class="sec-title">参数绑定（算法参数 → 本体）</div>
        <table class="tbl">
          <thead><tr><th class="w-44">算法参数</th><th class="w-24">类型</th><th class="w-44">绑定类型</th><th>绑定到</th></tr></thead>
          <tbody>
            <tr v-for="inp in algo?.inputs ?? []" :key="inp.name" class="!cursor-default">
              <td><span class="font-mono">{{ inp.name }}</span> {{ inp.label }}<span v-if="inp.required" class="text-err">*</span></td>
              <td class="text-fg-dim text-xs">{{ inp.type }}{{ inp.unit ? ' · ' + inp.unit : '' }}</td>
              <td>
                <select :value="form.bindings[inp.name]?.kind ?? ''" class="inp w-full" @change="setKind(inp.name, ($event.target as HTMLSelectElement).value)">
                  <option value="">（不绑定 / 用默认）</option>
                  <option v-for="(t, k) in ((meta?.bindingKinds ?? {}) as Record<string, string>)" :key="k" :value="k" :disabled="inp.type === '常量' ? k !== 'const' : k === 'const'">{{ t }}</option>
                </select>
              </td>
              <td>
                <template v-if="form.bindings[inp.name]?.kind === 'parameter'">
                  <select v-model="form.bindings[inp.name].name" class="inp w-56"><option value="">选择本对象参数</option><option v-for="p in params" :key="p.name" :value="p.name">{{ p.name }}（{{ p.kind }}）</option></select>
                  <input v-model="form.bindings[inp.name].index" type="number" min="0" class="inp w-24 ml-1" placeholder="第 n 个测点" title="一个参数有多个测点时取第几个（从 0 开始，空 = 全部）" />
                </template>
                <template v-else-if="form.bindings[inp.name]?.kind === 'groupParameter'">
                  <select v-model="form.bindings[inp.name].groupId" class="inp w-48"><option v-for="a in anchorOptions.filter((x) => x.kind === 'group')" :key="a.id" :value="a.id">{{ a.name }}</option></select>
                  <input v-model="form.bindings[inp.name].name" class="inp w-40 ml-1" placeholder="参数名" />
                </template>
                <input v-else-if="form.bindings[inp.name]?.kind === 'tag'" v-model="form.bindings[inp.name].tag" class="inp w-48 font-mono" placeholder="如 TI_1301C" />
                <select v-else-if="form.bindings[inp.name]?.kind === 'calc'" v-model="form.bindings[inp.name].calcId" class="inp w-64"><option v-for="x in allCalcs" :key="x.id" :value="x.id">{{ x.name }}（{{ x.id }}）</option></select>
                <input v-else-if="form.bindings[inp.name]?.kind === 'const'" v-model="form.bindings[inp.name].value" type="number" step="any" class="inp w-32" />
                <span v-else class="text-fg-mute text-xs">{{ inp.default !== undefined ? `默认 ${inp.default}` : '未绑定' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="sec-title">执行设置</div>
          <div class="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 items-center">
            <span class="text-xs text-fg-mute">执行方式</span>
            <div class="flex gap-1"><button v-for="m in meta?.modes ?? []" :key="m" class="ctl" :class="{ 'ctl-on': form.execution.mode === m }" @click="form.execution.mode = m">{{ m }}</button></div>
            <template v-if="form.execution.mode === '周期'"><span class="text-xs text-fg-mute">周期（秒）</span><input v-model="form.execution.periodSec" type="number" min="10" class="inp w-32" /></template>
            <template v-if="form.execution.mode === '事件触发'"><span class="text-xs text-fg-mute">触发事件</span><input v-model="form.execution.trigger" class="inp" placeholder="如：现象「水解罐pH偏高」成立 / 批次开始" /></template>
            <span class="text-xs text-fg-mute">超时（秒）</span><input v-model="form.execution.timeoutSec" type="number" min="1" class="inp w-32" />
            <span class="text-xs text-fg-mute">失败处理</span>
            <div class="flex items-center gap-1">
              <select v-model="form.execution.onFailure" class="inp w-24"><option v-for="m in meta?.failureModes ?? []" :key="m">{{ m }}</option></select>
              <template v-if="form.execution.onFailure === '重试'">重试 <input v-model="form.execution.retries" type="number" min="0" class="inp w-16" /> 次</template>
              ；连续失败 <input v-model="form.execution.disableAfter" type="number" min="1" class="inp w-16" /> 次自动停用
            </div>
          </div>
        </div>
        <div>
          <div class="sec-title">输出</div>
          <div class="grid grid-cols-[90px_1fr] gap-x-3 gap-y-2 items-center">
            <span class="text-xs text-fg-mute">输出测点</span><input v-model="form.output.tag" class="inp font-mono" placeholder="XBase 计算测点位号（待分配）" />
            <span class="text-xs text-fg-mute">写回 XBase</span>
            <label class="text-xs flex items-center gap-1"><input v-model="form.output.writeBack" type="checkbox" /> 计算结果写入输出测点，本体通过读测点获得结果</label>
            <span class="text-xs text-fg-mute">状态</span>
            <select v-model="form.status" class="inp w-48"><option>草案·待工艺确认</option><option>生效</option><option>停用</option></select>
          </div>
        </div>
      </div>
      <div class="text-[11px] text-fg-mute">本 Demo 没有调度器：执行设置只登记；「试算」按需运行一次（模拟数据）并记入运行记录。</div>
      <div v-if="error" class="text-err text-xs">{{ error }}</div>
    </div>
  </Modal>
</template>
