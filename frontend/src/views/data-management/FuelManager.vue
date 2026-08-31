<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { fuelsApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "pricePerLiter", label: "价格(元/升)", type: "number", required: true },
];
</script>
<template>
  <DataManager :api="fuelsApi" resource="fuels" title="燃料" :columns="columns" />
</template>
