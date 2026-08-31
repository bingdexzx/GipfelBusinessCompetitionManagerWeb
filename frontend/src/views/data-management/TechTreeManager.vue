<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { techNodesApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
  { prop: "description", label: "描述", type: "textarea" },
  { prop: "tier", label: "层级", type: "number" },
  { prop: "researchCost", label: "研发成本", type: "number" },
];
</script>
<template>
  <DataManager :api="techNodesApi" resource="tech-nodes" title="科技节点" :columns="columns" />
</template>
