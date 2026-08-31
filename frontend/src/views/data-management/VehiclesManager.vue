<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { vehiclesApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "fuelConsumptionPerKm", label: "油耗(L/km)", type: "number" },
  { prop: "maxCargo", label: "最大载重", type: "number" },
  { prop: "price", label: "价格", type: "number", required: true },
  { prop: "carbonEmission", label: "碳排", type: "number" },
];
</script>
<template>
  <DataManager :api="vehiclesApi" resource="vehicles" title="载具" :columns="columns" />
</template>
