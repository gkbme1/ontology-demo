<script setup lang="ts">
defineProps<{ title: string; wide?: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 overflow-auto" @mousedown.self="emit('close')">
      <div class="panel shadow-2xl w-full mt-6" :class="wide ? 'max-w-[1100px]' : 'max-w-[760px]'">
        <div class="panel-head">
          <h3 class="flex-1">{{ title }}</h3>
          <slot name="actions" />
          <button class="ctl" @click="emit('close')">关闭</button>
        </div>
        <div class="max-h-[78vh] overflow-auto px-4 pb-3.5">
          <div class="h-3.5" />
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>
