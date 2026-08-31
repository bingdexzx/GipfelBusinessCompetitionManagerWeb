import { createRouter, createWebHashHistory, type RouteRecordRaw } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { hasPermission } from "@/permissions/catalog";
import { versionBlocked } from "@/config";

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/dashboard" },
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/login/LoginView.vue"),
    meta: { public: true },
  },
  {
    path: "/",
    component: () => import("@/components/layout/AppLayout.vue"),
    meta: { requiresAuth: true },
    children: [
      {
        path: "dashboard",
        name: "dashboard",
        component: () => import("@/views/dashboard/DashboardView.vue"),
      },
      { path: "data", redirect: "/data/materials" },
      {
        path: "data/materials",
        name: "materials",
        component: () => import("@/views/data-management/MaterialsManager.vue"),
        meta: { permission: "data:material:view" },
      },
      {
        path: "data/parts",
        name: "parts",
        component: () => import("@/views/data-management/PartsManager.vue"),
        meta: { permission: "data:part:view" },
      },
      {
        path: "data/products",
        name: "products",
        component: () => import("@/views/data-management/ProductsManager.vue"),
        meta: { permission: "data:product:view" },
      },
      {
        path: "data/tech-tree",
        name: "techTree",
        component: () => import("@/views/data-management/TechTreeManager.vue"),
        meta: { permission: "data:tech:view" },
      },
      {
        path: "data/maps",
        name: "maps",
        component: () => import("@/views/data-management/MapsManager.vue"),
        meta: { permission: "data:map:view" },
      },
      {
        path: "data/infrastructures",
        name: "infrastructures",
        component: () => import("@/views/data-management/InfrastructureManager.vue"),
        meta: { permission: "data:infrastructure:view" },
      },
      {
        path: "data/fuels",
        name: "fuels",
        component: () => import("@/views/data-management/FuelManager.vue"),
        meta: { permission: "data:fuel:view" },
      },
      {
        path: "data/vehicles",
        name: "vehicles",
        component: () => import("@/views/data-management/VehiclesManager.vue"),
        meta: { permission: "data:vehicle:view" },
      },
      {
        path: "data/warehouses",
        name: "warehouses",
        component: () => import("@/views/data-management/WarehousesManager.vue"),
        meta: { permission: "data:warehouse:view" },
      },
      {
        path: "data/production-lines",
        name: "productionLines",
        component: () => import("@/views/data-management/ProductionLinesManager.vue"),
        meta: { permission: "data:productionLine:view" },
      },
      {
        path: "industry-types",
        name: "industryTypes",
        component: () => import("@/views/data-management/IndustryTypeManageView.vue"),
        meta: { permission: "industryType:view" },
      },
      {
        path: "companies",
        name: "companies",
        component: () => import("@/views/companies/CompanyListView.vue"),
        meta: { permission: "company:view" },
      },
      {
        path: "companies/:id",
        name: "companyDetail",
        component: () => import("@/views/companies/CompanyDetailView.vue"),
        meta: { permission: "company:view" },
      },
      {
        path: "contract-types",
        name: "contractTypes",
        component: () => import("@/views/data-management/ContractTypeManageView.vue"),
        meta: { permission: "contractType:view" },
      },
      {
        path: "contracts",
        name: "contracts",
        component: () => import("@/views/data-management/ContractManageView.vue"),
        meta: { permission: "contract:view" },
      },
      {
        path: "regions",
        name: "regions",
        component: () => import("@/views/regions/RegionOverviewView.vue"),
        meta: { permission: "data:region:view" },
      },
      {
        path: "messages",
        name: "messages",
        component: () => import("@/views/messages/MessageCenterView.vue"),
        meta: { permission: "message:view" },
      },
      {
        path: "stocks",
        name: "stockMarket",
        component: () => import("@/views/stocks/StockMarketView.vue"),
        meta: { permission: "stock:view" },
      },
      {
        path: "stocks/manage",
        name: "stockManage",
        component: () => import("@/views/stocks/StockManageView.vue"),
        meta: { permission: "stock:view" },
      },
      {
        path: "competitions",
        name: "competitions",
        component: () => import("@/views/competitions/CompetitionListView.vue"),
        meta: { permission: "competition:manage" },
      },
      {
        path: "accounts",
        name: "accounts",
        component: () => import("@/views/account-management/AccountManagementView.vue"),
        meta: { permission: "account:manage" },
      },
      {
        path: "settings",
        name: "settings",
        component: () => import("@/views/settings/SettingsView.vue"),
      },
    ],
  },
];

const router = createRouter({ history: createWebHashHistory(), routes });

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (versionBlocked.value && to.name !== "login") return { name: "login" };
  if (to.meta.public) return true;
  if (to.meta.requiresAuth && !auth.isAuthenticated) return { name: "login" };
  const perm = to.meta.permission as string | undefined;
  if (perm && !hasPermission(auth.user?.role, auth.user?.permissions ?? [], perm)) {
    return { name: "dashboard" };
  }
  return true;
});

export default router;
