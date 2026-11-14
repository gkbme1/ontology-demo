<script setup lang="ts">
/**
 * 处置规程（需求 ONTO-SR-SW-051、4.4 d）：处置卡按需求拆成三部分展示——
 * 报警现象 / 可能原因（→ 原因现象 + 导致关系，可逐条或一键拆分）/ 处置规程（步骤、处置前后检查项、执行边界、版本、状态，可编辑）。
 */
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { bump } from '@/composables/useNav'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ card: Any; open?: boolean; canEdit?: boolean; anchorId?: string }>()
const emit = defineEmits<{ (e: 'changed', card: Any): void; (e: 'phen', id: string): void }>()
const expanded = ref(!!props.open)
const editing = ref(false)
const form = ref<Any>(null)
const busy = ref(false)
const error = ref('')
const SPLIT_PILL: Record<string, string> = { 已拆分: 'pill-ok', 缺导致关系: 'pill-warn', 未拆分: 'pill-mute' }
const unsplit = computed(() => props.card.causes.filter((c: Any) => c.splitState !== '已拆分').length)

function startEdit(): void {
  form.value = JSON.parse(JSON.stringify({ steps: props.card.steps, checks: props.card.checks, autoExecution: props.card.autoExecution,
                                           authorization: props.card.authorization, version: props.card.version, status: props.card.status,
                                           scope: props.card.scope }))
  editing.value = true
  expanded.value = true
}
function addStep(): void {
  form.value.steps.push({ seq: String(form.value.steps.length + 1), phase: '', role: '', description: '', precondition: '', expected: '', caution: '', manualConfirm: true })
}
function addCheck(): void { form.value.checks.push({ when: '处置后', parameter: '', limitId: null, requirement: '' }) }
async function save(): Promise<void> {
  error.value = ''
  try {
    form.value.steps.forEach((s: Any, i: number) => (s.seq = String(i + 1)))
    const c = await api.updateProcedure(props.card.id, form.value)
    editing.value = false
    emit('changed', c)
  } catch (e) {
    error.value = String((e as Error).message)
  }
}
async function split(seq?: string): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    const r = seq ? await api.splitCause(props.card.id, seq, { anchorId: props.anchorId })
                  : await api.splitAllCauses(props.card.id, { anchorId: props.anchorId })
    bump()
    emit('changed', r.card)
  } catch (e) {
    error.value = String((e as Error).message)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="card">
    <div class="flex items-center gap-2 cursor-pointer" @click="expanded = !expanded">
      <span class="text-fg-mute">{{ expanded ? '▾' : '▸' }}</span>
      <span class="font-mono text-xs text-fg-mute">{{ card.id }}</span>
      <span class="font-medium">{{ card.name }}</span>
      <span v-if="card.trigger?.level" class="pill pill-err">{{ card.trigger.level }}</span>
      <span class="text-xs text-fg-dim">{{ card.trigger?.setpoint }} {{ card.trigger?.unit }}</span>
      <span class="flex-1" />
      <span class="text-[11px] text-fg-mute">原因 {{ card.causes.length }}（已拆分 {{ card.splitCount }}）· 步骤 {{ card.steps.length }} · {{ card.version }}</span>
      <span v-if="card.edited" class="pill pill-info" :title="`在线修改于 ${card.editedAt}`">已修改</span>
      <span class="pill pill-warn">{{ card.status }}</span>
    </div>
    <div v-if="expanded" class="mt-3 space-y-3 text-xs">
      <div v-if="canEdit" class="flex gap-1.5">
        <template v-if="!editing">
          <button class="btn" @click.stop="startEdit">编辑规程</button>
          <button v-if="unsplit" class="btn" :disabled="busy" title="把未拆分的可能原因建成原因现象 + 导致关系" @click.stop="split()">一键拆分剩余 {{ unsplit }} 条原因</button>
        </template>
        <template v-else>
          <button class="btn btn-primary" @click.stop="save">保存规程</button>
          <button class="btn" @click.stop="editing = false">取消</button>
        </template>
        <span v-if="error" class="text-err self-center">{{ error }}</span>
      </div>
      <dl class="kv">
        <dt>适用范围</dt>
        <dd><input v-if="editing" v-model="form.scope" class="inp w-full" /><template v-else>{{ card.scope }}</template></dd>
        <dt>报警现象</dt>
        <dd>
          <button v-for="p in card.alarmPhenomena" :key="p.id" class="phen-link mr-1" @click="emit('phen', p.id)">{{ p.name }}</button>
          <span v-if="!card.alarmPhenomena.length" class="text-fg-mute">还没有对应的现象（拆分原因时自动建，挂在本对象上）</span>
        </dd>
        <dt>触发位号</dt><dd class="font-mono">{{ (card.trigger?.tags ?? []).map((t: Any) => t.text).join('、') }}</dd>
        <dt>DCS 现象</dt><dd>{{ card.phenomena?.dcs }}</dd>
        <dt v-if="card.phenomena?.field">现场现象</dt><dd v-if="card.phenomena?.field">{{ card.phenomena.field }}</dd>
        <dt>未及时处置</dt><dd class="text-fg-dim">{{ card.consequence?.text }}</dd>
        <dt>版本 / 状态</dt>
        <dd>
          <template v-if="editing"><input v-model="form.version" class="inp w-32" /> <input v-model="form.status" class="inp w-48 ml-1" /></template>
          <template v-else>{{ card.version }} · {{ card.status }}</template>
        </dd>
        <dt>依据</dt><dd class="text-fg-mute">{{ card.basis }}</dd>
      </dl>

      <div v-if="card.causes.length">
        <div class="sec-title">可能原因 → 原因现象 + 导致关系（根因影响关系）</div>
        <table class="tbl">
          <thead><tr><th class="w-8">#</th><th class="w-14">类别</th><th>原因</th><th>核实方法 / 判据</th><th class="w-[220px]">本体中</th></tr></thead>
          <tbody>
            <tr v-for="c in card.causes" :key="c.seq" class="!cursor-default">
              <td class="text-fg-mute">{{ c.seq }}</td><td><span class="pill pill-plain">{{ c.category }}</span></td>
              <td>{{ c.description }}</td>
              <td class="text-fg-dim">{{ c.verifyMethod }}<div v-if="c.criterion" class="text-fg-mute">判据：{{ c.criterion }}</div></td>
              <td>
                <span class="pill" :class="SPLIT_PILL[c.splitState]">{{ c.splitState }}</span>
                <button v-if="c.phenomenon" class="phen-link ml-1" :title="c.phenomenon.hasRule ? '' : '判定规则待定义'" @click="emit('phen', c.phenomenon.id)">{{ c.phenomenon.name }}</button>
                <button v-else-if="canEdit" class="ctl ml-1" :disabled="busy" @click="split(c.seq)">拆分</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <div class="sec-title flex items-center gap-2">处置步骤 <button v-if="editing" class="ctl" @click="addStep">+ 步骤</button></div>
        <table class="tbl">
          <thead><tr><th class="w-8">#</th><th :class="editing ? 'w-28' : 'w-20'">阶段</th><th :class="editing ? 'w-28' : 'w-20'">角色</th><th :class="editing ? 'w-[28%]' : ''">操作说明</th><th>前置条件</th><th>预期结果</th><th>注意事项</th><th class="w-20">需人工确认</th><th v-if="editing" class="w-10"></th></tr></thead>
          <tbody>
            <template v-if="!editing">
              <tr v-for="s in card.steps" :key="s.seq" class="!cursor-default">
                <td class="text-fg-mute">{{ s.seq }}</td><td class="text-fg-dim">{{ s.phase }}</td><td class="text-fg-dim">{{ s.role }}</td>
                <td>{{ s.description }}</td><td class="text-fg-dim">{{ s.precondition || '—' }}</td>
                <td class="text-fg-dim">{{ s.expected || '—' }}</td><td class="text-fg-dim">{{ s.caution || '—' }}</td>
                <td><span class="pill" :class="s.manualConfirm ? 'pill-warn' : 'pill-plain'" :title="s.manualConfirm ? '' : '确认 / 对比类步骤，可由系统辅助判断'">{{ s.manualConfirm ? '是' : '系统辅助' }}</span></td>
              </tr>
            </template>
            <template v-else>
              <tr v-for="(s, i) in form.steps" :key="i" class="!cursor-default">
                <td class="text-fg-mute">{{ i + 1 }}</td>
                <td><input v-model="s.phase" class="inp w-full" /></td><td><input v-model="s.role" class="inp w-full" /></td>
                <td><textarea v-model="s.description" class="inp w-full" rows="2" /></td>
                <td><input v-model="s.precondition" class="inp w-full" /></td><td><input v-model="s.expected" class="inp w-full" /></td>
                <td><input v-model="s.caution" class="inp w-full" /></td>
                <td class="text-center"><input v-model="s.manualConfirm" type="checkbox" /></td>
                <td><button class="ctl !px-1.5" title="删除步骤" @click="form.steps.splice(i, 1)">×</button></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div>
        <div class="sec-title flex items-center gap-2">处置前后检查的参数与限值 <button v-if="editing" class="ctl" @click="addCheck">+ 检查项</button></div>
        <table class="tbl">
          <thead><tr><th class="w-20">时机</th><th class="w-40">参数</th><th class="w-20">限值</th><th>要求</th><th v-if="editing" class="w-10"></th></tr></thead>
          <tbody>
            <tr v-for="(k, i) in (editing ? form.checks : card.checks)" :key="i" class="!cursor-default">
              <template v-if="!editing">
                <td><span class="pill pill-plain">{{ k.when }}</span></td><td>{{ k.parameter }}</td>
                <td class="font-mono">{{ k.limitId ?? '—' }}</td><td class="text-fg-dim">{{ k.requirement }}</td>
              </template>
              <template v-else>
                <td><select v-model="k.when" class="inp w-full"><option>处置前</option><option>处置后</option></select></td>
                <td><input v-model="k.parameter" class="inp w-full" /></td><td><input v-model="k.limitId" class="inp w-full" /></td>
                <td><input v-model="k.requirement" class="inp w-full" /></td>
                <td><button class="ctl !px-1.5" @click="form.checks.splice(i, 1)">×</button></td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>

      <div>
        <div class="sec-title">执行边界</div>
        <dl class="kv">
          <dt>自动执行</dt><dd><input v-if="editing" v-model="form.autoExecution" class="inp w-full" /><span v-else class="text-err/90">{{ card.autoExecution }}</span></dd>
          <dt>授权要求</dt><dd><input v-if="editing" v-model="form.authorization" class="inp w-full" /><template v-else>{{ card.authorization }}</template></dd>
          <dt>禁止操作</dt>
          <dd><ul v-if="card.forbidden.length" class="list-disc pl-5 text-err/90"><li v-for="(f, i) in card.forbidden" :key="i">{{ f }}</li></ul><span v-else class="text-fg-mute">—</span></dd>
          <dt>解除条件</dt><dd class="text-fg-dim">{{ card.clearCondition }}</dd>
        </dl>
      </div>
    </div>
  </div>
</template>
