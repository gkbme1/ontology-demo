<script setup lang="ts">
/**
 * 「来源」列（需求 ONTO-SR-SW-026：逐行标识来源 类 / 设备组 / 本对象）：
 * 继承来的条目标「设备组」或「类」，本对象自有的标「本对象」。由本体推导，只读。
 */
import { computed } from 'vue'

const props = defineProps<{ checked?: boolean; from?: string | null }>()
const label = computed(() => {
  if (!props.checked) return '本对象'
  if ((props.from ?? '').startsWith('类')) return '类'
  return '设备组'
})
</script>

<template>
  <span class="inline-flex justify-center w-full">
    <span class="pill whitespace-nowrap cursor-help" :class="checked ? 'pill-info' : 'pill-plain'"
          :title="checked ? `继承自${from ?? '类对象'}` : '本对象自有'">{{ label }}</span>
  </span>
</template>
