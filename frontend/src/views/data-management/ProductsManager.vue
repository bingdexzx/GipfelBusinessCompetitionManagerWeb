<script setup lang="ts">
import DataManager, { type ColumnDef } from "@/components/common/DataManager.vue";
import { productsApi } from "@/api";

const columns: ColumnDef[] = [
  { prop: "name", label: "名称", required: true },
];
</script>
<template>
  <DataManager :api="productsApi" resource="products" title="产品" :columns="columns" />
</template>
