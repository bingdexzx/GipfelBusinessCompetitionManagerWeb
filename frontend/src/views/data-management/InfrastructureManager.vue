<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { infrastructuresApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "footprint", label: "占地", type: "number" },
  { prop: "price", label: "价格", type: "number", required: true },
  { prop: "activationPrice", label: "激活价", type: "number", required: true },
  { prop: "employmentRateBonus", label: "就业率加成", type: "number" },
  { prop: "populationBonus", label: "人口加成", type: "number" },
  { prop: "happinessIndexBonus", label: "幸福度加成", type: "number" },
];
</script>
<template>
  <DataManager :api="infrastructuresApi" resource="infrastructures" title="基建" :columns="columns" />
</template>
