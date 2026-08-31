<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { warehousesApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "capacity", label: "容量", type: "number", required: true },
  { prop: "price", label: "价格", type: "number", required: true },
  { prop: "type", label: "类型", type: "select", required: true, options: [
    { label: "原料", value: "MATERIAL" },
    { label: "零件", value: "PART" },
    { label: "产品", value: "PRODUCT" },
  ] },
];
</script>
<template>
  <DataManager :api="warehousesApi" resource="warehouses" title="仓库" :columns="columns" />
</template>
