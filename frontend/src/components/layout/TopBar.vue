<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";

const auth = useAuthStore();
const competition = useCompetitionStore();
const router = useRouter();

const displayName = computed(
  () => auth.user?.displayName || auth.user?.username || "用户",
);

function handleCompetitionChange(id: number | null) {
  competition.select(id);
}

async function handleLogout() {
  auth.logout();
  ElMessage.success("已退出登录");
  router.push("/login");
}
</script>

<template>
  <header class="topbar">
    <div class="left">
      <span class="title">商赛办赛辅助系统</span>
      <el-select
        v-if="competition.list.length"
        :model-value="competition.currentId"
        placeholder="选择比赛"
        size="default"
        style="width: 220px; margin-left: 24px"
        @change="handleCompetitionChange"
      >
        <el-option
          v-for="c in competition.list"
          :key="c.id"
          :label="c.name + (c.status === 'CLOSED' ? '（已结束）' : '')"
          :value="c.id"
        />
      </el-select>
    </div>
    <div class="right">
      <span class="role-tag">{{ auth.user?.role }}</span>
      <el-dropdown>
        <span class="user">
          <el-icon><User /></el-icon>
          {{ displayName }}
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="router.push('/settings')">系统设置</el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped lang="scss">
.topbar {
  height: 56px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}
.left {
  display: flex;
  align-items: center;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.role-tag {
  padding: 2px 8px;
  background: #ecf5ff;
  color: #409eff;
  border-radius: 4px;
  font-size: 12px;
}
.user {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #606266;
}
</style>
