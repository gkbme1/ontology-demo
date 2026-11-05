<script setup lang="ts">
/** 报警处置卡：触发、现象、后果、可能原因、处置步骤、禁止操作、解除条件。可折叠。 */
import { ref } from 'vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ card: Any; open?: boolean }>()
const expanded = ref(!!props.open)
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
      <span class="text-[11px] text-fg-mute">原因 {{ card.causes?.length ?? 0 }} · 步骤 {{ card.steps?.length ?? 0 }}</span>
      <span class="pill pill-warn">{{ card.status }}</span>
    </div>
    <div v-if="expanded" class="mt-3 space-y-3 text-xs">
      <dl class="kv">
        <dt>触发位号</dt><dd class="font-mono">{{ (card.trigger?.tags ?? []).map((t: Any) => t.text).join('、') }}</dd>
        <dt>DCS 现象</dt><dd>{{ card.phenomena?.dcs }}</dd>
        <dt v-if="card.phenomena?.field">现场现象</dt><dd v-if="card.phenomena?.field">{{ card.phenomena.field }}</dd>
        <dt>未及时处置</dt><dd class="text-fg-dim">{{ card.consequence?.text }}</dd>
        <dt>解除条件</dt><dd class="text-fg-dim">{{ card.clearCondition }}</dd>
        <dt>依据</dt><dd class="text-fg-mute">{{ card.basis }}</dd>
      </dl>
      <div v-if="card.causes?.length">
        <div class="sec-title">可能原因</div>
        <table class="tbl"><tbody>
          <tr v-for="c in card.causes" :key="c.seq" class="!cursor-default">
            <td class="w-8 text-fg-mute">{{ c.seq }}</td><td class="whitespace-nowrap"><span class="pill pill-plain">{{ c.category }}</span></td>
            <td>{{ c.description }}</td><td class="text-fg-dim">{{ c.verifyMethod }}</td><td class="text-fg-mute">{{ c.criterion }}</td>
          </tr>
        </tbody></table>
      </div>
      <div v-if="card.steps?.length">
        <div class="sec-title">处置步骤</div>
        <table class="tbl"><tbody>
          <tr v-for="s in card.steps" :key="s.seq" class="!cursor-default">
            <td class="w-8 text-fg-mute">{{ s.seq }}</td><td class="whitespace-nowrap text-fg-dim">{{ s.phase }}</td>
            <td class="whitespace-nowrap text-fg-dim">{{ s.role }}</td><td>{{ s.description }}</td>
          </tr>
        </tbody></table>
      </div>
      <div v-if="card.forbidden?.length">
        <div class="sec-title">禁止操作</div>
        <ul class="list-disc pl-5 text-err/90"><li v-for="f in card.forbidden" :key="f.seq">{{ f.text }}</li></ul>
      </div>
    </div>
  </div>
</template>
