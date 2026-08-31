<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { productionLinesApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "price", label: "价格", type: "number", required: true },
  { prop: "laborCount", label: "用工数", type: "number" },
  { prop: "maxPerYear", label: "年最大产能", type: "number" },
];
</script>
<template>
  <DataManager :api="productionLinesApi" resource="production-lines" title="生产线" :columns="columns" />
</template>
