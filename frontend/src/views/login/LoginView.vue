<script setup lang="ts">
import { ref, reactive } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";

const router = useRouter();
const auth = useAuthStore();
const competition = useCompetitionStore();

const form = reactive({ username: "", password: "" });
const loading = ref(false);
const showChangePassword = ref(false);
const changeForm = reactive({ oldPassword: "", newPassword: "", confirm: "" });

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  loading.value = true;
  try {
    const user = await auth.login(form.username, form.password);
    ElMessage.success("登录成功");
    if (user.mustChangePassword) {
      showChangePassword.value = true;
    } else {
      await competition.load();
      router.push("/dashboard");
    }
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    loading.value = false;
  }
}

async function handleChangePassword() {
  if (!changeForm.newPassword || changeForm.newPassword !== changeForm.confirm) {
    ElMessage.warning("两次输入的新密码不一致");
    return;
  }
  try {
    await auth.changePassword(changeForm.oldPassword, changeForm.newPassword);
    ElMessage.success("密码修改成功");
    showChangePassword.value = false;
    await competition.load();
    router.push("/dashboard");
  } catch {
    /* ignore */
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="title">Gipfel 商赛办赛辅助系统</h1>
      <p class="subtitle">请登录以继续</p>
      <el-form @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名"
            prefix-icon="User"
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>
      <p class="hint">默认管理员：admin / admin123（首次登录强制改密）</p>
    </div>

    <el-dialog v-model="showChangePassword" title="修改初始密码" :close-on-click-modal="false" :show-close="false">
      <el-form label-width="100px">
        <el-form-item label="原密码">
          <el-input v-model="changeForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="changeForm.newPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="changeForm.confirm" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="handleChangePassword">确认修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
}
.login-card {
  width: 380px;
  background: #fff;
  padding: 40px 32px;
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}
.title {
  text-align: center;
  font-size: 22px;
  margin: 0 0 8px;
  color: #303133;
}
.subtitle {
  text-align: center;
  color: #909399;
  margin: 0 0 24px;
  font-size: 14px;
}
.hint {
  text-align: center;
  color: #c0c4cc;
  font-size: 12px;
  margin-top: 16px;
}
</style>
