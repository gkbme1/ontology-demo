<script setup lang="ts">
/**
 * 报警处置卡：触发 / 可能原因 / 后果 / 处置步骤 / 解除条件 / 禁止操作 / 汇报与记录。
 * 卡片里提到的位号、工艺量、设备都已对应到本体（可点击跳转）；对应不上的标「待确认」。
 * 「可自动」表示有已对应的位号，可由程序直接用本体的实时 / 历史值完成；其余为给人的指引。
 */
import { computed } from 'vue'
import type { ProcAnchor, ProcedureCard } from '@/api/types'

const props = defineProps<{ card: ProcedureCard }>()
const emit = defineEmits<{ open: [objectId: string] }>()

const PHASES = ['确认判断', '假报警处置', '真实处置', '升级上报', '恢复确认']
const stepGroups = computed(() => {
  const groups: { phase: string; steps: ProcedureCard['steps'] }[] = []
  for (const s of props.card.steps) {
    let g = groups.find((x) => x.phase === s.phase)
    if (!g) groups.push((g = { phase: s.phase, steps: [] }))
    g.steps.push(s)
  }
  return groups.sort((a, b) => PHASES.indexOf(a.phase) - PHASES.indexOf(b.phase))
})
const onlyConfirmSteps = computed(() => props.card.steps.every((s) => s.phase === '确认判断'))

const CAT_STYLE: Record<string, string> = {
  仪表: 'pill-info', 工艺: 'pill-ok', 设备: 'pill-warn', 操作: 'pill-err', 公用工程: 'pill-plain'
}
const openable = (a: ProcAnchor) => !!a.id && a.status === '已对应'
function open(a: ProcAnchor) {
  if (openable(a)) emit('open', a.id as string)
}
function shown(list: ProcAnchor[], n = 10) {
  return { items: list.slice(0, n), more: Math.max(0, list.length - n) }
}
</script>

<template>
  <div class="space-y-3 text-[12.5px]">
    <!-- 头部 -->
    <div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="font-mono text-equip">{{ card.id }}</span>
        <span class="text-[14px] font-semibold">{{ card.name }}</span>
        <span class="pill" :class="card.status.startsWith('草案') ? 'pill-warn' : 'pill-ok'">{{ card.status }}</span>
        <span v-if="card.relation" class="pill pill-plain">{{ card.relation }}</span>
      </div>
      <div class="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-fg-dim">
        <span v-if="card.alarmName"><span class="text-fg-mute">报警 </span>{{ card.alarmName }}</span>
        <span v-if="card.trigger.level"><span class="text-fg-mute">级别 </span>{{ card.trigger.level }}</span>
        <span v-if="card.trigger.setpoint"><span class="text-fg-mute">设定值 </span><span class="text-fg">{{ card.trigger.setpoint }} {{ card.trigger.unit }}</span></span>
        <span v-if="card.trigger.limits.length"><span class="text-fg-mute">工艺限值 </span><span class="font-mono">{{ card.trigger.limits.map((l) => l.id).join('、') }}</span></span>
        <span v-if="card.priority"><span class="text-fg-mute">优先级 </span>{{ card.priority }}</span>
        <span v-if="card.responseTime"><span class="text-fg-mute">允许响应 </span>{{ card.responseTime }}</span>
        <span v-if="card.area.text"><span class="text-fg-mute">工段 </span>{{ card.area.text }}</span>
      </div>
      <div class="mt-1 text-[11.5px] text-fg-mute">
        可能原因 {{ card.summary.causeCount }}（可自动验证 {{ card.summary.autoCauseCount }}）·
        处置步骤 {{ card.summary.stepCount }}（可自动 {{ card.summary.autoStepCount }}）·
        本体对应 {{ card.summary.anchored }} 处<template v-if="card.summary.pending"> / <span class="text-warn">待确认 {{ card.summary.pending }}</span></template>
      </div>
    </div>

    <!-- 触发 -->
    <div class="rounded border border-line-soft bg-ink-panel2/40 px-3 py-2">
      <div class="text-fg-mute text-[11px] mb-1">触发</div>
      <div class="flex flex-wrap items-center gap-1">
        <button v-for="a in card.trigger.objects" :key="'o' + a.text" class="pill" :class="openable(a) ? 'pill-info cursor-pointer' : 'pill-mute'" :title="a.status" @click="open(a)">{{ a.text }}</button>
        <span class="text-fg-mute mx-1">位号</span>
        <button v-for="a in shown(card.trigger.tags, 14).items" :key="'t' + a.text" class="pill font-mono" :class="openable(a) ? 'pill-plain cursor-pointer' : 'pill-mute'" :title="a.label ?? a.status" @click="open(a)">{{ a.text }}</button>
        <span v-if="shown(card.trigger.tags, 14).more" class="pill pill-plain">+{{ shown(card.trigger.tags, 14).more }}</span>
      </div>
      <div v-if="card.interlocks.length" class="mt-1"><span class="text-fg-mute">关联联锁 / 报警事件 </span>
        <button v-for="a in card.interlocks" :key="a.text" class="pill mr-1" :class="openable(a) ? 'pill-err cursor-pointer' : 'pill-mute'" @click="open(a)">{{ a.text }}</button></div>
      <div v-if="card.phenomena.dcs || card.phenomena.field" class="mt-1 text-fg-dim">
        <div v-if="card.phenomena.dcs"><span class="text-fg-mute">现象·DCS </span>{{ card.phenomena.dcs }}</div>
        <div v-if="card.phenomena.field"><span class="text-fg-mute">现象·现场 </span>{{ card.phenomena.field }}</div>
      </div>
    </div>

    <!-- 可能原因 -->
    <div>
      <div class="text-fg-mute text-[11px] mb-1">可能原因 · 验证方法</div>
      <table class="tbl">
        <thead><tr><th class="w-[64px]">类别</th><th>原因</th><th>验证方法 · 位号</th><th class="w-[180px]">判据</th><th class="w-[64px]">验证</th></tr></thead>
        <tbody>
          <tr v-for="c in card.causes" :key="c.seq" class="!cursor-default">
            <td><span class="pill" :class="CAT_STYLE[c.category] ?? 'pill-plain'">{{ c.category }}</span></td>
            <td>{{ c.description }}
              <div v-if="c.objects.length" class="mt-0.5 flex flex-wrap gap-1">
                <button v-for="a in c.objects" :key="a.text" class="text-[11px]" :class="openable(a) ? 'text-info hover:underline' : 'text-fg-mute'" @click="open(a)">{{ a.text }}</button>
              </div></td>
            <td class="text-fg-dim">{{ c.verifyMethod || '—' }}
              <div v-if="c.verifyTags.length" class="mt-0.5 flex flex-wrap gap-1">
                <button v-for="a in shown(c.verifyTags, 6).items" :key="a.text" class="pill font-mono" :class="openable(a) ? 'pill-info cursor-pointer' : 'pill-mute'" :title="a.label ?? a.status" @click="open(a)">{{ a.text }}</button>
                <span v-if="shown(c.verifyTags, 6).more" class="pill pill-plain">+{{ shown(c.verifyTags, 6).more }}</span>
              </div></td>
            <td class="text-fg-dim text-[12px]">{{ c.criterion || '—' }}</td>
            <td><span class="pill" :class="c.autoCheck ? 'pill-ok' : 'pill-mute'">{{ c.autoCheck ? '可自动' : '人工' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 后果 -->
    <div v-if="card.consequence.text">
      <div class="text-fg-mute text-[11px] mb-1">未及时处置后果</div>
      <div class="text-fg-dim">{{ card.consequence.text }}</div>
      <div v-if="card.consequence.objects.length" class="mt-1 flex flex-wrap gap-1">
        <button v-for="a in card.consequence.objects" :key="a.text" class="pill" :class="openable(a) ? 'pill-plain cursor-pointer' : 'pill-mute'" @click="open(a)">{{ a.text }}</button>
      </div>
    </div>

    <!-- 处置步骤 -->
    <div>
      <div class="text-fg-mute text-[11px] mb-1">处置步骤</div>
      <div v-for="g in stepGroups" :key="g.phase" class="mb-2">
        <div class="font-semibold text-[12px] mb-0.5">{{ g.phase }}</div>
        <div v-for="s in g.steps" :key="s.seq" class="flex gap-2 py-1 pl-2 border-l-2" :class="s.auto ? 'border-ok/60' : 'border-line'">
          <span class="pill pill-plain shrink-0">{{ s.role || '—' }}</span>
          <span class="pill shrink-0" :class="s.auto ? 'pill-ok' : 'pill-mute'">{{ s.action || '—' }}{{ s.auto ? ' · 可自动' : '' }}</span>
          <div class="min-w-0">
            <div>{{ s.description }}</div>
            <div v-if="s.precondition" class="text-warn text-[11.5px]">前置：{{ s.precondition }}</div>
            <div v-if="s.tags.length" class="mt-0.5 flex flex-wrap gap-1">
              <button v-for="a in shown(s.tags, 8).items" :key="a.text" class="pill font-mono" :class="openable(a) ? 'pill-info cursor-pointer' : 'pill-mute'" @click="open(a)">{{ a.text }}</button>
              <span v-if="shown(s.tags, 8).more" class="pill pill-plain">+{{ shown(s.tags, 8).more }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="onlyConfirmSteps" class="text-warn text-[12px]">真实处置、升级上报、恢复确认等步骤待工艺人员在 6APA_处置规程.xlsx 中补充。</div>
    </div>

    <!-- 解除 / 禁止 / 汇报 / 记录 -->
    <div class="grid gap-3 md:grid-cols-2">
      <div>
        <div class="text-fg-mute text-[11px] mb-1">解除条件</div>
        <div class="text-fg-dim">{{ card.clearCondition || '待补充' }}</div>
      </div>
      <div>
        <div class="text-fg-mute text-[11px] mb-1">禁止操作</div>
        <div v-if="!card.forbidden.length" class="text-fg-mute">待工艺补充</div>
        <div v-for="f in card.forbidden" :key="f.seq + f.text" class="text-err">⛔ {{ f.text }}</div>
      </div>
      <div>
        <div class="text-fg-mute text-[11px] mb-1">汇报要点</div>
        <div class="text-fg-dim">{{ card.reportPoints || '—' }}</div>
      </div>
      <div>
        <div class="text-fg-mute text-[11px] mb-1">记录要求</div>
        <div class="text-fg-dim">{{ card.recordRequirement || '—' }}</div>
      </div>
    </div>
    <div class="text-fg-mute text-[11px]">依据：{{ card.basis || '—' }} · 来源 {{ card.source?.file }} 第 {{ card.source?.row }} 行</div>
  </div>
</template>
