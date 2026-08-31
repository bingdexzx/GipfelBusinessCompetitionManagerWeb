<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";
import { competitionsApi } from "@/api";

const auth = useAuthStore();
const competition = useCompetitionStore();
const stats = ref({ companies: 0, contracts: 0, messages: 0, stocks: 0 });

onMounted(async () => {
  if (!competition.list.length) await competition.load();
});
</script>

<template>
  <div class="dashboard page-container">
    <h2>欢迎，{{ auth.user?.displayName || auth.user?.username }}</h2>
    <p v-if="competition.current">当前比赛：<b>{{ competition.current.name }}</b></p>
    <p v-else style="color: #e6a23c">尚未选择比赛，请在顶部切换或前往「比赛管理」创建。</p>

    <el-row :gutter="16" style="margin-top: 24px">
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-title">公司数量</div>
          <div class="stat-value">{{ stats.companies }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-title">合同数量</div>
          <div class="stat-value">{{ stats.contracts }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-title">未读消息</div>
          <div class="stat-value">{{ stats.messages }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="stat-card">
          <div class="stat-title">股票数量</div>
          <div class="stat-value">{{ stats.stocks }}</div>
        </div>
      </el-col>
    </el-row>

    <div class="card mt-16">
      <h3>系统说明</h3>
      <p>Gipfel 商赛办赛辅助系统（Web 版）——办赛方通过本系统维护竞赛全量标准化数据、配置比赛参数，
        并通过配置驱动的合同引擎与可视化编辑能力高效运作赛事。</p>
      <p>请在左侧菜单选择功能模块。数据管理需先在顶部选择比赛上下文。</p>
    </div>
  </div>
</template>

<style scoped lang="scss">
.stat-card {
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  padding: 16px;
}
.stat-title {
  color: #909399;
  font-size: 13px;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #409eff;
  margin-top: 8px;
}
</style>
