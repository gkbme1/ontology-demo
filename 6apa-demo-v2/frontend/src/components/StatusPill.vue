<script setup lang="ts">
/** 现象 / 导致关系 / 计算组态的状态：草案（草案·待工艺确认）/ 生效 / 停用（需求 ONTO-SR-SW-062）。 */
defineProps<{ status?: string }>()
</script>

<template>
  <span v-if="status === '生效'" class="pill pill-ok">生效</span>
  <span v-else-if="status === '停用'" class="pill pill-mute">停用</span>
  <span v-else class="pill pill-warn" :title="status">草案</span>
</template>
