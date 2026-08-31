<script setup lang="ts">
import { computed } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { hasPermission } from "@/permissions/catalog";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

interface MenuItem {
  title: string;
  index: string;
  icon?: string;
  permission?: string;
  children?: MenuItem[];
}

const menus = computed<MenuItem[]>(() => [
  { title: "仪表盘", index: "/dashboard", icon: "Odometer" },
  {
    title: "数据管理",
    index: "data",
    icon: "Files",
    children: [
      { title: "原料管理", index: "/data/materials", permission: "data:material:view" },
      { title: "零件管理", index: "/data/parts", permission: "data:part:view" },
      { title: "产品管理", index: "/data/products", permission: "data:product:view" },
      { title: "科技树", index: "/data/tech-tree", permission: "data:tech:view" },
      { title: "地图管理", index: "/data/maps", permission: "data:map:view" },
      { title: "基建管理", index: "/data/infrastructures", permission: "data:infrastructure:view" },
      { title: "燃料管理", index: "/data/fuels", permission: "data:fuel:view" },
      { title: "载具管理", index: "/data/vehicles", permission: "data:vehicle:view" },
      { title: "仓库管理", index: "/data/warehouses", permission: "data:warehouse:view" },
      { title: "生产线管理", index: "/data/production-lines", permission: "data:productionLine:view" },
    ],
  },
  {
    title: "产业与合同",
    index: "industry",
    icon: "Connection",
    children: [
      { title: "产业类型", index: "/industry-types", permission: "industryType:view" },
      { title: "公司管理", index: "/companies", permission: "company:view" },
      { title: "合同类型", index: "/contract-types", permission: "contractType:view" },
      { title: "合同管理", index: "/contracts", permission: "contract:view" },
    ],
  },
  { title: "区域总览", index: "/regions", icon: "Location", permission: "data:region:view" },
  { title: "消息中心", index: "/messages", icon: "Message", permission: "message:view" },
  { title: "股票市场", index: "/stocks", icon: "TrendCharts", permission: "stock:view" },
  { title: "股票管理", index: "/stocks/manage", icon: "Money", permission: "stock:view" },
  { title: "比赛管理", index: "/competitions", icon: "Trophy", permission: "competition:manage" },
  { title: "账户管理", index: "/accounts", icon: "User", permission: "account:manage" },
  { title: "系统设置", index: "/settings", icon: "Setting" },
]);

const visibleMenus = computed<MenuItem[]>(() => {
  const filter = (items: MenuItem[]): MenuItem[] => {
    const result: MenuItem[] = [];
    for (const it of items) {
      if (it.permission && !hasPermission(auth.user?.role, auth.user?.permissions ?? [], it.permission)) {
        continue;
      }
      const copy: MenuItem = { ...it };
      if (it.children) {
        copy.children = filter(it.children);
        if (copy.children.length === 0) continue;
      }
      result.push(copy);
    }
    return result;
  };
  return filter(menus.value);
});

const activeIndex = computed(() => route.path);

function handleSelect(index: string) {
  if (index.startsWith("/")) router.push(index);
}

function parentActive(item: MenuItem): string {
  if (item.children?.some((c) => c.index === route.path)) return item.index;
  return "";
}
</script>

<template>
  <aside class="sidebar">
    <div class="logo">Gipfel 商赛系统</div>
    <el-menu
      :default-active="activeIndex"
      :default-openeds="['data', 'industry']"
      background-color="#001529"
      text-color="#bdc3cf"
      active-text-color="#fff"
      @select="handleSelect"
    >
      <template v-for="item in visibleMenus" :key="item.index">
        <el-sub-menu v-if="item.children" :index="item.index">
          <template #title>
            <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
          </template>
          <el-menu-item v-for="c in item.children" :key="c.index" :index="c.index">
            {{ c.title }}
          </el-menu-item>
        </el-sub-menu>
        <el-menu-item v-else :index="item.index">
          <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </template>
    </el-menu>
  </aside>
</template>

<style scoped lang="scss">
.sidebar {
  width: 220px;
  background: #001529;
  color: #fff;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  border-bottom: 1px solid #1f2d3d;
}
:deep(.el-menu) {
  border-right: none;
  flex: 1;
}
</style>
