<script setup lang="ts">
/** 对象基础信息与变更记录（需求 SW-041 第 4、5 条，SW-062）。 */
import { ref } from 'vue'
import { api } from '@/api/client'
import { staticBackend } from '@/api/static'
import { enterSegment, nav, openDrawing } from '@/composables/useNav'
import Modal from './Modal.vue'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
const props = defineProps<{ objectId: string; opId?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const info = ref<Any>(null)
const error = ref('')
api.objectInfo(props.objectId, props.opId).then((r) => (info.value = r)).catch((e) => (error.value = String(e.message)))
function goSeg(id: string): void { emit('close'); enterSegment(id) }
function goDrawing(op: string): void { emit('close'); openDrawing(op, nav.meta?.opSegment?.[op]) }
</script>

<template>
  <Modal :title="`基础信息 · ${info?.name ?? ''}`" wide @close="emit('close')">
    <div v-if="error" class="text-err">{{ error }}</div>
    <div v-else-if="!info" class="text-fg-mute">加载中…</div>
    <div v-else class="grid grid-cols-2 gap-4 text-sm">
      <div class="card">
        <div class="sec-title">基础信息</div>
        <dl class="kv">
          <dt>对象 ID</dt><dd class="font-mono">{{ info.id }}</dd>
          <dt>编码</dt><dd class="font-mono">{{ info.code || '—' }}</dd>
          <dt>类型</dt><dd>{{ info.kind }}</dd>
          <dt>类</dt><dd>{{ info.className || '—' }}<div v-if="info.classPath" class="text-[11px] text-fg-mute">{{ info.classPath.join(' › ') }}</div></dd>
          <dt>状态</dt><dd>{{ info.status }}</dd>
          <dt>来源</dt><dd>{{ info.source }}<span v-if="info.confidence" class="text-fg-mute"> · 归属置信度 {{ info.confidence }}</span></dd>
          <dt>测点 / 现象</dt><dd>{{ info.tagCount }} 个 DCS 点 · {{ info.phenomenonCount }} 个现象（含继承）</dd>
        </dl>
      </div>
      <div class="card">
        <div class="sec-title">所属位置</div>
        <dl class="kv">
          <dt>空间层级</dt>
          <dd><template v-for="(p, i) in info.path" :key="p.id">
            <button v-if="p.id.startsWith('SEG-')" class="text-brand" @click="goSeg(p.id)">{{ p.name }}</button><span v-else>{{ p.name }}</span><span v-if="i < info.path.length - 1"> › </span>
          </template></dd>
          <dt>资产分类</dt><dd>{{ info.assetPath.join(' › ') || '—' }}</dd>
          <dt>设备组</dt><dd>{{ info.group?.name ?? '—' }}</dd>
          <dt>所在图纸</dt>
          <dd><button v-for="d in info.drawings" :key="d.opId" class="ctl mr-1" @click="goDrawing(d.opId)">{{ d.name }}{{ d.hasImage ? '（现场图纸）' : '（示意图）' }}</button></dd>
        </dl>
      </div>
      <div class="card">
        <div class="sec-title">被引用</div>
        <div class="text-xs space-y-1">
          <div><span class="text-fg-mute">其他对象的现象规则引用本对象位号：</span>
            <span v-if="!info.referencedBy.phenomena.length" class="text-fg-mute">无</span>
            <span v-for="p in info.referencedBy.phenomena" :key="p.id" class="pill pill-plain mr-1">{{ p.name }}（{{ p.anchor }}）</span></div>
          <div><span class="text-fg-mute">计算组态：</span>
            <span v-if="!info.referencedBy.calculations.length" class="text-fg-mute">无</span>
            <span v-for="c in info.referencedBy.calculations" :key="c.id" class="pill pill-plain mr-1">{{ c.name }} · {{ c.how }}</span></div>
          <div><span class="text-fg-mute">人工新增关系：</span>
            <span v-if="!info.referencedBy.relations.length" class="text-fg-mute">无</span>
            <span v-for="r in info.referencedBy.relations" :key="r.id" class="pill pill-plain mr-1">{{ r.text }}</span></div>
        </div>
      </div>
      <div class="card">
        <div class="sec-title">本台覆盖 / 禁用的继承项</div>
        <div v-if="!info.overrides.length" class="text-xs text-fg-mute">无（全部沿用设备组 / 类的定义）</div>
        <div v-for="o in info.overrides" :key="o.kind + o.id" class="text-xs py-0.5">
          <span class="pill" :class="o.state === '已禁用' ? 'pill-mute' : 'pill-warn'">{{ o.state }}</span> {{ o.kind }} {{ o.id }}
          <span class="text-fg-mute">{{ o.at }}{{ o.note ? ' · ' + o.note : '' }}</span>
        </div>
      </div>
      <div class="card col-span-2">
        <div class="sec-title">变更记录（本对象及其现象，最新在前）</div>
        <div v-if="staticBackend" class="text-xs text-fg-mute">单文件版不记录变更</div>
        <div v-else-if="!info.changes.length" class="text-xs text-fg-mute">暂无变更（种子数据之后的在线编辑会记录在这里）</div>
        <table v-else class="tbl">
          <thead><tr><th class="w-36">时间</th><th class="w-20">操作人</th><th class="w-24">操作</th><th>对象</th><th>变更字段（前 → 后）</th></tr></thead>
          <tbody>
            <tr v-for="c in info.changes" :key="c.id" class="!cursor-default">
              <td class="text-xs tabular-nums">{{ c.time }}</td><td class="text-xs">{{ c.user }}</td>
              <td><span class="pill pill-plain">{{ c.op }}</span></td>
              <td class="text-xs">{{ c.kind }} · {{ c.name }}<div v-if="c.note" class="text-fg-mute">{{ c.note }}</div></td>
              <td class="text-xs">
                <div v-for="d in c.changes" :key="d.field" class="truncate max-w-[520px]" :title="`${d.before} → ${d.after}`">
                  <span class="text-fg-mute">{{ d.field }}：</span>{{ d.before ?? '—' }} → {{ d.after ?? '—' }}
                </div>
                <span v-if="!c.changes.length" class="text-fg-mute">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </Modal>
</template>
