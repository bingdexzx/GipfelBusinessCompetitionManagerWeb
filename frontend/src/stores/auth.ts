import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { authApi } from "@/api";
import {
  getAccountItem,
  setAccountItem,
  removeAccountItem,
  setRealm,
  clearAccountStorage,
} from "@/utils/accountStorage";
import { connectRealtime, disconnectRealtime, subscribeCompetition } from "@/realtime/socket";
import { hasPermission } from "@/permissions/catalog";

export interface UserProfile {
  id: number;
  username: string;
  role: string;
  displayName?: string | null;
  mustChangePassword: boolean;
  permissions: string[];
  companyScopes: number[];
  viewCompanyScopes: number[];
  contractViewCompanyScopes: number[];
  stockCompanyScopes: number[];
  competitionId: number | null;
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(getAccountItem("token"));
  const user = ref<UserProfile | null>(null);
  const isAuthenticated = computed(() => !!token.value && !!user.value);
  const isSuperAdmin = computed(() => user.value?.role === "SUPER_ADMIN");
  const needsPasswordChange = computed(() => !!user.value?.mustChangePassword);

  /** 权限判定：SUPER_ADMIN 隐式拥有全部；其余按 actionRank 等级蕴含（与后端 hasPermission 一致）。 */
  function can(perm: string): boolean {
    return hasPermission(user.value?.role, user.value?.permissions ?? [], perm);
  }
  /** 持有给定权限中的任意一个（含同域蕴含） */
  function canAny(perms: string[]): boolean {
    return perms.some((p) => can(p));
  }
  /** 是否为某公司的合同审核员/管理员（合同审核范围判断） */
  function canAuditCompany(companyId: number): boolean {
    if (user.value?.role === "SUPER_ADMIN") return true;
    const owned = user.value?.permissions ?? [];
    if (owned.includes("contract:execute") || owned.includes("contract:manage")) return true;
    if (!owned.includes("contract:audit")) return false;
    return (user.value?.companyScopes ?? []).includes(companyId);
  }

  async function login(username: string, password: string) {
    const res: any = await authApi.login(username, password);
    token.value = res.token;
    user.value = res.user as UserProfile;
    setRealm(`${res.user.username}@${res.user.competitionId ?? 0}`);
    setAccountItem("token", res.token);
    setAccountItem("user", JSON.stringify(res.user));
    connectRealtime();
    if (res.user.competitionId) subscribeCompetition(res.user.competitionId);
    return res.user;
  }

  async function restore() {
    const cached = getAccountItem("user");
    if (cached) {
      try {
        user.value = JSON.parse(cached);
      } catch {
        user.value = null;
      }
    }
    if (token.value) {
      try {
        const me: any = await authApi.me();
        user.value = me;
        setAccountItem("user", JSON.stringify(me));
        setRealm(`${me.username}@${me.competitionId ?? 0}`);
        connectRealtime();
        if (me.competitionId) subscribeCompetition(me.competitionId);
      } catch {
        logout();
      }
    }
  }

  function logout() {
    token.value = null;
    user.value = null;
    removeAccountItem("token");
    removeAccountItem("user");
    clearAccountStorage();
    disconnectRealtime();
  }

  async function changePassword(oldPassword: string, newPassword: string) {
    await authApi.changePassword(oldPassword, newPassword);
    if (user.value) {
      user.value = { ...user.value, mustChangePassword: false };
      setAccountItem("user", JSON.stringify(user.value));
    }
  }

  /** 重新拉取当前用户资料（权限被管理员改动后由实时事件触发） */
  async function refreshProfile() {
    if (!token.value) return;
    try {
      const me: any = await authApi.me();
      user.value = me;
      setAccountItem("user", JSON.stringify(me));
    } catch {
      /* ignore */
    }
  }

  // 兼容原 store 命名：fetchProfile = restore；权限目录由本地 catalog 计算，无需远端拉取
  const fetchProfile = restore;
  async function fetchPermissionCatalog() {
    /* 权限目录前端镜像于 @/permissions/catalog，无需后端拉取 */
  }

  return {
    token,
    user,
    isAuthenticated,
    isSuperAdmin,
    needsPasswordChange,
    can,
    canAny,
    canAuditCompany,
    login,
    restore,
    fetchProfile,
    refreshProfile,
    fetchPermissionCatalog,
    logout,
    changePassword,
  };
});
