<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { partsApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
];
</script>
<template>
  <DataManager :api="partsApi" resource="parts" title="零件" :columns="columns" />
</template>
