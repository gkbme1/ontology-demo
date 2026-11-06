<script setup lang="ts">
/** 「继承」列：勾选 = 该条继承自类对象（设备组 / 设备类型模板）。由本体推导，只读。 */
defineProps<{ checked?: boolean; from?: string | null }>()
</script>

<template>
  <label class="inline-flex items-center justify-center w-full" :title="checked ? `继承自${from ?? '类对象'}` : '本对象自有'">
    <input type="checkbox" class="w-3.5 h-3.5 accent-[#0e8fa3] cursor-help" :checked="!!checked" @click.prevent />
  </label>
</template>
