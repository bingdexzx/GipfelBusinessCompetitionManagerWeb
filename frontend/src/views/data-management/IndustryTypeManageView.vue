<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { industryTypesApi } from "@/api";
import { deleteConfirm } from "@/utils/deleteConfirm";
import { onResourceChanged } from "@/realtime/resource-changed";

const loading = ref(false);
const list = ref<any[]>([]);
const dialogVisible = ref(false);
const editing = ref<any | null>(null);
const form = ref<any>({});

async function load() {
  loading.value = true;
  try {
    const res: any = await industryTypesApi.list();
    list.value = Array.isArray(res) ? res : res?.items ?? [];
  } catch {
    list.value = [];
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  form.value = { code: 0, name: "" };
  dialogVisible.value = true;
}

function openEdit(row: any) {
  editing.value = row;
  form.value = { ...row };
  dialogVisible.value = true;
}

async function save() {
  if (!form.value.name || form.value.code == null) {
    ElMessage.warning("请填写名称与编码");
    return;
  }
  try {
    if (editing.value) {
      await industryTypesApi.update(editing.value.id, form.value);
      ElMessage.success("更新成功");
    } else {
      await industryTypesApi.create(form.value);
      ElMessage.success("创建成功");
    }
    dialogVisible.value = false;
    await load();
  } catch {
    /* ignore */
  }
}

async function remove(row: any) {
  if (!(await deleteConfirm(`确定删除产业类型「${row.name}」？`))) return;
  await industryTypesApi.delete(row.id);
  ElMessage.success("删除成功");
  await load();
}

onMounted(() => {
  load();
  onResourceChanged("industry-types", () => load());
});
</script>

<template>
  <div class="page-container">
    <div class="toolbar">
      <span>产业类型管理</span>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建</el-button>
    </div>
    <el-table :data="list" border v-loading="loading">
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="code" label="编码" width="100" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="description" label="描述" />
      <el-table-column label="更新时间">
        <template #default="{ row }">{{ $formatTime(row.updatedAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑产业类型' : '新建产业类型'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="编码" required><el-input-number v-model="form.code" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
</style>
