<script setup lang="ts">
/** 开发态通用表单：按字段定义渲染「标签 + 输入」行（文本 / 数字 / 下拉 / 勾选 / 多行 / 多选 / 列表）。 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any
export interface Field { key: string; label: string; type?: string; options?: (string | { value: string; label: string })[]; readonly?: boolean; hint?: string; placeholder?: string; wide?: boolean }
const props = defineProps<{ fields: Field[]; model: Any; disabled?: boolean; cols?: number }>()
const opt = (o: Any) => (typeof o === 'string' ? { value: o, label: o } : o)
function toggle(f: Field, v: string): void {
  const arr: string[] = Array.isArray(props.model[f.key]) ? [...props.model[f.key]] : []
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(v)
  props.model[f.key] = arr
}
function listText(v: Any): string { return Array.isArray(v) ? v.join('、') : (v ?? '') }
function setList(f: Field, t: string): void { props.model[f.key] = t.split(/[、,，|]/).map((x) => x.trim()).filter(Boolean) }
</script>

<template>
  <div class="grid gap-x-4 gap-y-2 items-center text-sm" :class="(cols ?? 1) === 2 ? 'grid-cols-[96px_1fr_96px_1fr]' : 'grid-cols-[96px_1fr]'">
    <template v-for="f in fields" :key="f.key">
      <span class="text-xs text-fg-mute text-right" :class="{ 'self-start pt-1.5': f.type === 'textarea' || f.type === 'multi' }">{{ f.label }}</span>
      <div :class="{ 'col-span-3': f.wide && (cols ?? 1) === 2 }">
        <select v-if="f.type === 'select'" v-model="model[f.key]" class="inp w-full" :disabled="disabled || f.readonly">
          <option v-for="o in f.options ?? []" :key="opt(o).value" :value="opt(o).value">{{ opt(o).label }}</option>
        </select>
        <label v-else-if="f.type === 'bool'" class="inline-flex items-center gap-1.5 text-xs">
          <input v-model="model[f.key]" type="checkbox" :disabled="disabled || f.readonly" /> {{ f.hint ?? '是' }}
        </label>
        <textarea v-else-if="f.type === 'textarea'" v-model="model[f.key]" class="inp w-full" rows="2" :disabled="disabled || f.readonly" :placeholder="f.placeholder" />
        <div v-else-if="f.type === 'multi'" class="flex flex-wrap gap-1.5">
          <button v-for="o in f.options ?? []" :key="opt(o).value" type="button" class="ctl !py-0.5"
                  :class="{ 'ctl-on': (model[f.key] ?? []).includes(opt(o).value) }" :disabled="disabled || f.readonly" @click="toggle(f, opt(o).value)">{{ opt(o).label }}</button>
        </div>
        <input v-else-if="f.type === 'list'" :value="listText(model[f.key])" class="inp w-full" :disabled="disabled || f.readonly"
               :placeholder="f.placeholder ?? '用「、」分隔'" @change="setList(f, ($event.target as HTMLInputElement).value)" />
        <input v-else-if="f.type === 'number'" v-model.number="model[f.key]" type="number" step="any" class="inp w-full" :disabled="disabled || f.readonly" :placeholder="f.placeholder" />
        <input v-else v-model="model[f.key]" class="inp w-full" :class="{ 'font-mono': f.type === 'code' }" :disabled="disabled || f.readonly" :placeholder="f.placeholder" />
        <div v-if="f.hint && f.type !== 'bool'" class="text-[11px] text-fg-mute mt-0.5">{{ f.hint }}</div>
      </div>
    </template>
  </div>
</template>
