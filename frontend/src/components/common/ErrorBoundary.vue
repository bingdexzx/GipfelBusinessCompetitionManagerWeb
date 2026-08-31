<template>
  <div v-if="error" class="error-boundary">
    <el-result icon="error" :title="title" :sub-title="errorMessage">
      <template #extra>
        <el-button type="primary" @click="retry">重试本页</el-button>
        <el-button @click="goHome">返回首页</el-button>
      </template>
    </el-result>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
import { ref } from "vue";
import { onErrorCaptured } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

const router = useRouter();
const error = ref<Error | null>(null);
const errorMessage = ref("");
const title = ref("页面渲染出错");

/**
 * 捕获默认插槽（当前路由页面）渲染/生命周期中抛出的异常。
 * 返回 false 阻止错误继续向上冒泡到应用根，避免整应用白屏。
 * 同时把真实错误打到控制台，便于定位根因。
 */
onErrorCaptured((err, instance, info) => {
  const e = err as Error;
  // eslint-disable-next-line no-console
  console.error(
    "[ErrorBoundary] 捕获到页面渲染异常：",
    e,
    "\n组件实例：",
    instance,
    "\n错误位置(info)：",
    info,
  );
  error.value = e;
  errorMessage.value =
    (e && e.message ? e.message : String(err)) +
    "（该页面已隔离保护，其它界面仍可正常使用）";
  // 不向上冒泡，避免连带拖垮整个应用
  return false;
});

/** 重试：清空错误状态并整页重载当前路由，彻底重置该页面的响应式状态。 */
function retry(): void {
  error.value = null;
  router.go(0);
}

/** 返回首页：清空错误状态并跳转到仪表盘。 */
function goHome(): void {
  error.value = null;
  router.push("/").catch(() => {
    ElMessage.warning("已在首页");
  });
}
</script>

<style scoped>
.error-boundary {
  width: 100%;
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
</style>
