<template>
  <div class="topbar">
    <div class="topbar-left">
      <el-button
        v-if="showMenuToggle"
        class="menu-toggle"
        aria-label="打开菜单"
        @click="$emit('toggle')"
      >
        <el-icon :size="20"><Menu /></el-icon>
      </el-button>
      <!-- 抽屉模式(平板/手机)：左侧栏收起时，当前比赛与财年直接显示在顶栏，避免仅藏在抽屉侧栏中 -->
      <div v-if="isCompact" class="topbar-context">
        <template v-if="compStore.competitionName">
          <el-tag type="success" size="small" effect="plain" class="ctx-tag ctx-name">{{
            compStore.competitionName
          }}</el-tag>
          <el-tag
            v-if="compStore.fiscalYearLoading"
            type="info"
            size="small"
            effect="plain"
            class="ctx-tag ctx-loading"
          >
            <el-icon class="is-loading"><Loading /></el-icon> 财年加载中…
          </el-tag>
          <el-tag
            v-else-if="compStore.currentFiscalYear !== null"
            type="primary"
            size="small"
            effect="plain"
            class="ctx-tag"
            >第 {{ compStore.currentFiscalYear }} 财年</el-tag
          >
          <el-tag v-else type="warning" size="small" effect="plain" class="ctx-tag">未开启财年</el-tag>
        </template>
        <span v-else class="ctx-hint">
          未选择比赛 — <router-link to="/competitions">比赛管理</router-link>
        </span>
      </div>
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentTitle">{{ currentTitle }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    <div class="topbar-right">
      <span class="user-info">
        <span class="user-name">{{ authStore.user?.displayName || authStore.user?.username || "用户" }}</span>
        <el-tag size="small" :type="roleTagType" class="role-tag">{{ roleLabel }}</el-tag>
      </span>
      <el-button size="small" type="danger" plain style="margin-left: 16px" @click="handleLogout"
        >退出</el-button
      >
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Menu, Loading } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";
import { useBreakpoint } from "@/composables/useBreakpoint";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const compStore = useCompetitionStore();
const { isCompact } = useBreakpoint();

// 由父级 AppLayout 注入：平板/手机（抽屉模式）下显示汉堡按钮
const props = defineProps<{
  showMenuToggle?: boolean;
}>();
const emit = defineEmits<{
  toggle: [];
}>();

const currentTitle = computed(() => {
  const title = route.meta?.title as string | undefined;
  if (!title) return "";
  const managePerm = route.meta?.managePermission as string | undefined;
  if (managePerm && !authStore.can(managePerm) && title.endsWith("管理")) {
    return title.slice(0, -2);
  }
  return title;
});

const roleLabel = computed(() => {
  const map: Record<string, string> = {
    SUPER_ADMIN: "超管",
    COMPETITION_ADMIN: "管理员",
    PLAYER: "选手",
  };
  return map[authStore.user?.role || ""] || "";
});

const roleTagType = computed(() => {
  const map: Record<string, string> = {
    SUPER_ADMIN: "danger",
    COMPETITION_ADMIN: "warning",
    PLAYER: "info",
  };
  return map[authStore.user?.role || ""] || "info";
});

function handleLogout() {
  authStore.logout();
  router.push("/login");
}
</script>

<style scoped>
.topbar {
  height: var(--topbar-height);
  background: var(--glass-bg-strong);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--color-border);
  box-shadow:
    0 1px 0 rgba(16, 24, 40, 0.02),
    0 4px 16px rgba(16, 24, 40, 0.04);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--content-padding);
  flex-shrink: 0;
  position: relative;
  z-index: 5;
}
.topbar::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent 0%, rgba(99, 102, 241, 0.15) 30%, rgba(139, 92, 246, 0.15) 70%, transparent 100%);
  pointer-events: none;
}
.topbar-left {
  display: flex;
  align-items: center;
  min-width: 0;
}
.topbar-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.menu-toggle {
  margin-right: 6px;
  color: var(--color-text-secondary);
  /* 左上角汉堡按钮改为正方形：固定等宽高、内边距清零、图标居中、带边框浅底 */
  width: 36px !important;
  height: 36px !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border: 1px solid var(--color-border, #e4e7ed) !important;
  border-radius: 6px !important;
  background: var(--el-fill-color-blank, #fff) !important;
}
.menu-toggle:hover {
  color: var(--color-primary);
  border-color: var(--color-primary, #409eff) !important;
  background: var(--el-fill-color-light, #f5f7fa) !important;
}
/* 手机/平板(抽屉)模式：左上角正方形按钮整体往左靠，贴近屏幕左缘（比之前的 -6px 更靠左） */
@media (max-width: 1024px) {
  .menu-toggle {
    margin-left: -12px !important;
  }
}
/* 抽屉模式(平板/手机)顶栏上下文：当前比赛 + 财年，直接可见，避免藏在抽屉侧栏；
   外部套框，与电脑模式侧栏 .brand-meta 的呈现一致（边框 + 浅灰底 + 圆角） */
.topbar-context {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
  /* 平板/手机(抽屉)模式下，套框与右侧标题(面包屑)之间留出间距，避免紧贴 */
  margin-right: 12px;
  padding: 3px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: #f7f8fa;
}
.topbar-context .ctx-tag {
  flex-shrink: 0;
  height: 22px;
  line-height: 20px;
}
.topbar-context .ctx-name {
  flex-shrink: 1;
  max-width: 38vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-context .ctx-loading .el-icon {
  vertical-align: -2px;
  margin-right: 3px;
}
.topbar-context .ctx-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
}
.topbar-context .ctx-hint a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}
.topbar-context .ctx-hint a:hover {
  text-decoration: underline;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text-primary);
  min-width: 0;
}
/* 显示名称：过长时省略，避免与角色标签/退出按钮挤爆顶栏 */
.user-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.role-tag {
  font-size: 11px;
  height: 20px;
  line-height: 18px;
}
/* 手机(≤640px)：隐藏面包屑（显示名 + 角色标签 + 退出 与电脑模式一致，均保留） */
@media (max-width: 640px) {
  .topbar-left .el-breadcrumb {
    display: none;
  }
}
</style>
