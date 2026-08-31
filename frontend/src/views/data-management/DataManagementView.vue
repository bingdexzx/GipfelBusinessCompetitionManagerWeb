<template>
  <component :is="managerComponent" v-bind="currentConfig as any" v-if="currentConfig" />
  <component :is="managerComponent" v-else-if="isManagerType" />
  <div v-else class="placeholder">
    <h2>{{ title }}</h2>
    <p>此模块正在开发中</p>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, type Component } from "vue";
import { useRoute } from "vue-router";
import { moduleConfigs } from "@/config/dataModules";

const route = useRoute();
const type = computed(() => (route.meta?.type as string) || "");
const title = computed(() => (route.meta?.title as string) || "");

// 一次性创建所有异步组件引用，避免 computed 里每次调用 defineAsyncComponent 工厂
// 导致每次渲染返回新引用，Vue 反复判定组件类型变化、卸载重挂载、陷入 loading 死循环。
const MANAGER_COMPONENTS: Record<string, Component> = {
  maps: defineAsyncComponent(() => import("./MapsManager.vue")),
  parts: defineAsyncComponent(() => import("./PartsManager.vue")),
  products: defineAsyncComponent(() => import("./ProductsManager.vue")),
  vehicles: defineAsyncComponent(() => import("./VehiclesManager.vue")),
  "tech-tree": defineAsyncComponent(() => import("./TechTreeManager.vue")),
  materials: defineAsyncComponent(() => import("./MaterialsManager.vue")),
  warehouses: defineAsyncComponent(() => import("./WarehousesManager.vue")),
  "production-lines": defineAsyncComponent(() =>
    import("./ProductionLinesManager.vue"),
  ),
  infrastructures: defineAsyncComponent(() =>
    import("./InfrastructureManager.vue"),
  ),
  fuels: defineAsyncComponent(() => import("./FuelManager.vue")),
};
const DEFAULT_MANAGER: Component = defineAsyncComponent(() =>
  import("@/components/common/DataManager.vue"),
);

const MANAGER_TYPES = Object.keys(MANAGER_COMPONENTS);

const isManagerType = computed(() => MANAGER_TYPES.includes(type.value as string));

const currentConfig = computed(() =>
  isManagerType.value ? null : moduleConfigs[type.value] || null,
);

const managerComponent = computed(
  () => MANAGER_COMPONENTS[type.value as string] ?? DEFAULT_MANAGER,
);
</script>

<style scoped>
.placeholder {
  padding: 24px;
}
.placeholder h2 {
  position: relative;
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
  padding-left: 14px;
  margin: 0 0 8px;
}
.placeholder h2::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  border-radius: 4px;
  background: var(--gradient-brand);
}
.placeholder p {
  font-size: 14px;
  color: #8c8c8c;
}
</style>
