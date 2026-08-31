import { createRouter, createWebHashHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

declare module "vue-router" {
  interface RouteMeta {
    title?: string;
    type?: string;
    requiresPermission?: string;
    requiresSuperAdmin?: boolean;
    /** 拥有该权限时标题保留「管理」二字，否则去掉 */
    managePermission?: string;
  }
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/login",
      name: "Login",
      component: () => import("@/views/login/LoginView.vue"),
      meta: { title: "登录" },
    },
    {
      path: "/",
      component: () => import("@/components/layout/AppLayout.vue"),
      redirect: "/dashboard",
      children: [
        {
          path: "dashboard",
          name: "Dashboard",
          component: () => import("@/views/dashboard/DashboardView.vue"),
          meta: { title: "仪表盘" },
        },
        {
          path: "materials",
          name: "Materials",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "原料管理",
            type: "materials",
            requiresPermission: "data:material:view",
            managePermission: "data:material:edit",
          },
        },
        {
          path: "parts",
          name: "Parts",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "零件管理",
            type: "parts",
            requiresPermission: "data:part:view",
            managePermission: "data:part:edit",
          },
        },
        {
          path: "products",
          name: "Products",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "产品管理",
            type: "products",
            requiresPermission: "data:product:view",
            managePermission: "data:product:edit",
          },
        },
        {
          path: "maps",
          name: "Maps",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "地图管理",
            type: "maps",
            requiresPermission: "data:map:view",
            managePermission: "data:map:edit",
          },
        },
        {
          path: "infrastructures",
          name: "Infrastructures",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "基建管理",
            type: "infrastructures",
            requiresPermission: "data:infrastructure:view",
            managePermission: "data:infrastructure:edit",
          },
        },
        {
          path: "tech-tree",
          name: "TechTree",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "科技树管理",
            type: "tech-tree",
            requiresPermission: "data:tech:view",
            managePermission: "data:tech:edit",
          },
        },
        {
          path: "fuels",
          name: "Fuels",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "燃料管理",
            type: "fuels",
            requiresPermission: "data:fuel:view",
            managePermission: "data:fuel:edit",
          },
        },
        {
          path: "vehicles",
          name: "Vehicles",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "载具管理",
            type: "vehicles",
            requiresPermission: "data:vehicle:view",
            managePermission: "data:vehicle:edit",
          },
        },
        {
          path: "warehouses",
          name: "Warehouses",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "仓库管理",
            type: "warehouses",
            requiresPermission: "data:warehouse:view",
            managePermission: "data:warehouse:edit",
          },
        },
        {
          path: "production-lines",
          name: "ProductionLines",
          component: () => import("@/views/data-management/DataManagementView.vue"),
          meta: {
            title: "生产线管理",
            type: "production-lines",
            requiresPermission: "data:productionLine:view",
            managePermission: "data:productionLine:edit",
          },
        },
        {
          path: "region-overview",
          name: "RegionOverview",
          component: () => import("@/views/regions/RegionOverviewView.vue"),
          meta: { title: "区域总览", requiresPermission: "data:region:view" },
        },
        {
          path: "industry-types",
          name: "IndustryTypes",
          component: () => import("@/views/data-management/IndustryTypeManageView.vue"),
          meta: {
            title: "产业类型管理",
            requiresPermission: "industryType:manage",
            managePermission: "industryType:manage",
          },
        },
        {
          path: "messages",
          name: "Messages",
          component: () => import("@/views/messages/MessageCenterView.vue"),
          meta: {
            title: "消息中心",
            requiresPermission: "message:view",
            managePermission: "message:manage",
          },
        },
        {
          path: "contract-types",
          name: "ContractTypes",
          component: () => import("@/views/data-management/ContractTypeManageView.vue"),
          meta: {
            title: "合同类型管理",
            requiresPermission: "contractType:manage",
            managePermission: "contractType:manage",
          },
        },
        {
          path: "contracts",
          name: "Contracts",
          component: () => import("@/views/data-management/ContractManageView.vue"),
          meta: {
            title: "合同管理",
            requiresPermission: "contract:view",
            managePermission: "contract:manage",
          },
        },
        {
          path: "competitions",
          name: "Competitions",
          component: () => import("@/views/competitions/CompetitionListView.vue"),
          meta: {
            title: "比赛管理",
            requiresPermission: "competition:manage",
            managePermission: "competition:manage",
          },
        },
        {
          path: "accounts",
          name: "Accounts",
          component: () => import("@/views/account-management/AccountManagementView.vue"),
          meta: {
            title: "账户管理",
            requiresPermission: "account:manage",
            managePermission: "account:manage",
          },
        },
        {
          path: "settings",
          name: "Settings",
          component: () => import("@/views/settings/SettingsView.vue"),
          meta: { title: "系统设置" },
        },
        {
          path: "companies",
          name: "Companies",
          component: () => import("@/views/companies/CompanyListView.vue"),
          meta: {
            title: "公司管理",
            requiresPermission: "company:view",
            managePermission: "company:manage",
          },
        },
        {
          path: "companies/:id",
          name: "CompanyDetail",
          component: () => import("@/views/companies/CompanyDetailView.vue"),
          meta: { title: "公司详情", requiresPermission: "company:view" },
        },
        {
          path: "stocks",
          name: "Stocks",
          component: () => import("@/views/stocks/StockMarketView.vue"),
          meta: { title: "股票行情", requiresPermission: "stock:view" },
        },
        {
          path: "stock-management",
          name: "StockManagement",
          component: () => import("@/views/stocks/StockManageView.vue"),
          meta: {
            title: "股票管理",
            requiresPermission: "stock:edit",
            managePermission: "stock:manage",
          },
        },
      ],
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/dashboard",
    },
  ],
});

// vue-router 5 起导航守卫不再提供 next 回调，改用返回值控制跳转：
// 返回路径字符串表示重定向，返回 true（或不返回）表示放行，返回 false 表示取消。
router.beforeEach((to) => {
  const authStore = useAuthStore();
  // 强制改密：已登录但需改密的账号，统一停在登录页触发改密对话框，优先于其他跳转。
  if (authStore.isLoggedIn && authStore.needsPasswordChange) {
    if (to.path !== "/login") return "/login";
    return true;
  }
  if (to.path !== "/login" && !authStore.isLoggedIn) {
    return "/login";
  }
  if (to.path === "/login" && authStore.isLoggedIn) {
    return "/dashboard";
  }
  if (to.meta.requiresSuperAdmin && authStore.user?.role !== "SUPER_ADMIN") {
    return "/dashboard";
  }
  if (to.meta.requiresPermission && !authStore.can(to.meta.requiresPermission as string)) {
    return "/dashboard";
  }
  return true;
});

export default router;
