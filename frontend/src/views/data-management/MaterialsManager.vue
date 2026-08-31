<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { materialsApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true, placeholder: "原料名称" },
  { prop: "origin", label: "产地", required: true },
  { prop: "carbonEmissionCoefficient", label: "碳排系数", type: "number" },
  { prop: "type", label: "类型", type: "select", options: [
    { label: "普通", value: "NORMAL" },
    { label: "特殊", value: "SPECIAL" },
  ], default: "NORMAL" },
];

function defaultForm() {
  return { type: "NORMAL", carbonEmissionCoefficient: 0, nodePrices: "{}" };
}
</script>

<template>
  <DataManager
    :api="materialsApi"
    resource="materials"
    title="原料"
    :columns="columns"
    :default-form="defaultForm"
  />
</template>
