<template>
  <div class="message-center">
    <div class="mm-toolbar">
      <h2 class="mm-title">消息中心</h2>
      <div class="mm-actions">
        <el-button :icon="Refresh" @click="refresh">刷新</el-button>
        <el-button
          v-if="activeTab === 'inbox'"
          :icon="Check"
          :disabled="messageStore.unreadCount === 0"
          @click="markAllRead"
          >全部标为已读</el-button
        >
        <el-button
          v-if="activeTab === 'sent' && canManage"
          type="primary"
          :icon="Promotion"
          @click="openPublish"
          >发布消息</el-button
        >
      </div>
    </div>

    <el-tabs v-model="activeTab" class="msg-tabs" @tab-change="onTabChange">
      <el-tab-pane name="inbox">
        <template #label>
          <span class="tab-label">
            收件箱
            <el-badge
              v-if="messageStore.unreadCount > 0"
              :value="messageStore.unreadCount"
              :max="99"
              type="danger"
              class="tab-badge"
            />
          </span>
        </template>
        <div class="list-wrap">
          <div v-if="loading" class="empty-tip"><el-icon class="is-loading"><Loading /></el-icon> 加载中…</div>
          <div v-else-if="!inboxItems.length" class="empty-tip">暂无消息</div>
          <div
            v-for="item in inboxItems"
            :key="item.recipientId"
            class="msg-card"
            :class="{ unread: !item.read }"
            @click="markRead(item)"
          >
            <span class="read-dot" :class="{ on: !item.read }"></span>
            <div class="msg-main">
              <div class="msg-row">
                <span class="msg-title">{{ item.message.title }}</span>
                <span class="msg-sender">{{ item.senderName }}</span>
                <span class="msg-time">{{ formatTime(item.message.createdAt) }}</span>
              </div>
              <div class="msg-content">{{ item.message.content }}</div>
              <div
                v-if="item.message.images && item.message.images.length"
                class="msg-images"
                @click.stop
              >
                <el-image
                  v-for="(img, i) in item.message.images"
                  :key="img.filename"
                  :src="imgSrc(img)"
                  :preview-src-list="item.message.images.map(imgSrc)"
                  :initial-index="i"
                  fit="cover"
                  preview-teleported="true"
                  class="msg-img"
                />
              </div>
            </div>
            <el-tag v-if="!item.read" size="small" type="primary" effect="plain" class="unread-tag"
              >未读</el-tag
            >
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="canManage" name="sent">
        <template #label><span class="tab-label">已发布</span></template>
        <div class="list-wrap">
          <div v-if="loading" class="empty-tip"><el-icon class="is-loading"><Loading /></el-icon> 加载中…</div>
          <div v-else-if="!sentItems.length" class="empty-tip">尚未发布任何消息</div>
          <div v-for="item in sentItems" :key="item.id" class="msg-card sent">
            <div class="msg-main">
              <div class="msg-row">
                <span class="msg-title">{{ item.title }}</span>
                <span class="msg-time">{{ formatTime(item.createdAt) }}</span>
              </div>
              <div class="msg-content">{{ item.content }}</div>
              <div v-if="item.images && item.images.length" class="msg-images">
                <el-image
                  v-for="(img, i) in item.images"
                  :key="img.filename"
                  :src="imgSrc(img)"
                  :preview-src-list="item.images.map(imgSrc)"
                  :initial-index="i"
                  fit="cover"
                  preview-teleported="true"
                  class="msg-img"
                />
              </div>
              <div class="msg-meta">
                <el-tag size="small" effect="plain" type="info"
                  >接收 {{ item._count.recipients }} 人</el-tag
                >
                <el-tag v-if="item.targetsAll" size="small" effect="plain" type="success"
                  >本比赛全体</el-tag
                >
              </div>
            </div>
            <el-button
              class="del-btn"
              :icon="Delete"
              text
              type="danger"
              @click.stop="deleteSent(item)"
              >删除</el-button
            >
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 发布消息对话框 -->
    <el-dialog v-model="publishVisible" title="发布消息" width="560px" append-to-body @closed="resetPublish">
      <el-form ref="publishFormRef" :model="publishForm" :rules="publishRules" label-width="92px">
        <el-form-item label="标题" prop="title">
          <el-input v-model="publishForm.title" maxlength="80" show-word-limit placeholder="请输入消息标题" />
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <el-input
            v-model="publishForm.content"
            type="textarea"
            :rows="5"
            maxlength="2000"
            show-word-limit
            placeholder="请输入消息内容"
          />
        </el-form-item>
        <el-form-item v-if="isSuperAdmin" label="按比赛筛选" prop="filterCompetitionId">
          <el-select
            v-model="publishForm.filterCompetitionId"
            placeholder="不筛选（全部比赛）"
            clearable
            filterable
            style="width: 100%"
            @change="onFilterCompetitionChange"
          >
            <el-option
              v-for="c in competitions"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="本比赛全部">
          <el-switch v-model="publishForm.targetsAll" />
          <span class="form-hint">开启后向范围内全部账号发送，下方选择失效。</span>
        </el-form-item>
        <el-form-item label="接收账号" prop="targetUserIds">
          <el-select
            v-model="publishForm.targetUserIds"
            multiple
            filterable
            :disabled="publishForm.targetsAll"
            placeholder="选择接收账号"
            style="width: 100%"
          >
            <el-option
              v-for="u in selectableUsers"
              :key="u.id"
              :label="u.displayName || u.username"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="图片">
          <div class="img-uploader">
            <div class="img-grid">
              <div v-for="(img, i) in publishForm.images" :key="img.filename" class="img-thumb">
                <el-image :src="imgSrc(img)" :preview-src-list="previewList" :initial-index="i" fit="cover" preview-teleported="true" />
                <el-button
                  class="img-del"
                  :icon="Close"
                  circle
                  size="small"
                  type="danger"
                  @click="removeImage(i)"
                />
              </div>
              <label class="img-add" :class="{ disabled: uploadingImg }">
                <el-icon v-if="!uploadingImg"><Plus /></el-icon>
                <el-icon v-else class="is-loading"><Loading /></el-icon>
                <input
                  ref="imgInput"
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  :disabled="uploadingImg"
                  @change="onPickImages"
                />
              </label>
            </div>
            <span class="form-hint">可选，最多 9 张，单张 ≤ 15MB（PNG / JPEG / GIF / WebP / BMP）。</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="publishVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPublish">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  Refresh,
  Promotion,
  Loading,
  Check,
  Delete,
  Plus,
  Close,
} from "@element-plus/icons-vue";
import api, { messagesApi, type InboxItem, type SentItem, type MessageImage } from "@/api";
import { getApiBaseUrl } from "@/config";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";
import { useMessageStore } from "@/stores/message";

const authStore = useAuthStore();
const compStore = useCompetitionStore();
const messageStore = useMessageStore();

const activeTab = ref<"inbox" | "sent">("inbox");
const loading = ref(false);
const inboxItems = ref<InboxItem[]>([]);
const sentItems = ref<SentItem[]>([]);

const canManage = computed(() => authStore.can("message:manage"));
const isSuperAdmin = computed(() => authStore.isSuperAdmin);

// ---------- 数据加载 ----------
async function loadInbox() {
  loading.value = true;
  try {
    inboxItems.value = await messagesApi.inbox();
  } catch (e) {
    console.error("加载收件箱失败:", e);
  } finally {
    loading.value = false;
    // 进入收件箱后以服务端权威未读数刷新红点（标读动作另行递减）。
    messageStore.fetchUnread();
  }
}

async function loadSent() {
  loading.value = true;
  try {
    sentItems.value = await messagesApi.sent();
  } catch (e) {
    console.error("加载已发布失败:", e);
  } finally {
    loading.value = false;
  }
}

function refresh() {
  if (activeTab.value === "inbox") loadInbox();
  else loadSent();
}

function onTabChange() {
  if (activeTab.value === "inbox") loadInbox();
  else loadSent();
}

async function markRead(item: InboxItem) {
  if (item.read) return;
  try {
    await messagesApi.markRead(item.message.id);
    item.read = true;
    if (messageStore.unreadCount > 0) messageStore.unreadCount--;
  } catch (e) {
    console.error("标记已读失败:", e);
  }
}

async function markAllRead() {
  try {
    await messageStore.markAllRead();
    inboxItems.value.forEach((i) => (i.read = true));
  } catch (e) {
    console.error("全部已读失败:", e);
  }
}

async function deleteSent(item: SentItem) {
  try {
    await ElMessageBox.confirm(`确认删除消息《${item.title}》？`, "删除确认", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await messagesApi.remove(item.id);
    sentItems.value = sentItems.value.filter((s) => s.id !== item.id);
    ElMessage.success("已删除");
  } catch (e) {
    console.error("删除失败:", e);
    ElMessage.error("删除失败");
  }
}

// ---------- 发布对话框 ----------
const publishVisible = ref(false);
const submitting = ref(false);
const publishFormRef = ref<any>(null);
const selectableUsers = ref<{ id: number; username: string; displayName?: string }[]>([]);
const competitions = ref<{ id: number; name: string }[]>([]);

const publishForm = reactive({
  title: "",
  content: "",
  targetsAll: false,
  targetUserIds: [] as number[],
  filterCompetitionId: undefined as number | undefined,
  images: [] as MessageImage[],
});

const uploadingImg = ref(false);
const imgInput = ref<any>(null);

/** 图片完整地址：服务端根 + 相对路径（静态文件经 /uploads 托管，前端跨源加载）。 */
function imgSrc(img: MessageImage) {
  return getApiBaseUrl() + img.url;
}

/** 发布对话框预览列表（随 images 变化）。 */
const previewList = computed(() => publishForm.images.map(imgSrc));

/** 选择图片后逐张上传，成功追加到 images；超 9 张或单张失败给出提示。 */
async function onPickImages(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = input.files ? Array.from(input.files) : [];
  if (!files.length) return;
  if (publishForm.images.length + files.length > 9) {
    ElMessage.warning("最多添加 9 张图片");
    files.splice(9 - publishForm.images.length);
  }
  uploadingImg.value = true;
  try {
    for (const f of files) {
      const meta = await messagesApi.uploadImage(f);
      publishForm.images.push(meta);
    }
  } catch (err: any) {
    console.error("上传图片失败:", err);
    ElMessage.error(err?.response?.data?.message || "图片上传失败");
  } finally {
    uploadingImg.value = false;
    input.value = "";
  }
}

/** 从待发布列表移除某张图片。 */
function removeImage(i: number) {
  publishForm.images.splice(i, 1);
}

const publishRules = {
  title: [{ required: true, message: "请输入标题", trigger: "blur" }],
  content: [{ required: true, message: "请输入内容", trigger: "blur" }],
  targetUserIds: [
    {
      validator: (_r: any, value: number[], cb: (e?: Error) => void) => {
        if (!publishForm.targetsAll && (!value || value.length === 0)) {
          cb(new Error("请至少选择一个接收账号，或开启「本比赛全部」"));
        } else {
          cb();
        }
      },
      trigger: "change",
    },
  ],
};

function resetPublish() {
  publishForm.title = "";
  publishForm.content = "";
  publishForm.targetsAll = false;
  publishForm.targetUserIds = [];
  publishForm.filterCompetitionId = undefined;
  publishForm.images = [];
  selectableUsers.value = [];
  publishFormRef.value?.clearValidate?.();
}

async function openPublish() {
  if (isSuperAdmin.value) {
    try {
      competitions.value = await api.get("/competitions").then((res: any) =>
        Array.isArray(res) ? res : res?.items ?? [],
      );
    } catch {
      competitions.value = [];
    }
    // 默认把「按比赛筛选」指向当前正在浏览的比赛，使「本比赛全体」精确指向该比赛，
    // 避免超管未注意下拉而误发全站。清空下拉仍可主动触发全站广播（提交时会二次确认）。
    publishForm.filterCompetitionId = compStore.competitionId || undefined;
  }
  await loadSelectableUsers();
  publishVisible.value = true;
}

async function loadSelectableUsers() {
  try {
    const cid = isSuperAdmin.value ? publishForm.filterCompetitionId : undefined;
    selectableUsers.value = await messagesApi.selectableUsers(cid);
  } catch (e) {
    console.error("加载可选账号失败:", e);
    selectableUsers.value = [];
  }
}

function onFilterCompetitionChange() {
  loadSelectableUsers();
  publishForm.targetUserIds = [];
}

async function submitPublish() {
  try {
    await publishFormRef.value.validate();
  } catch {
    return;
  }
  // 超管开启「本比赛全体」但未指定比赛 → 将广播全站（含其他比赛），强制二次确认避免误发。
  if (isSuperAdmin.value && publishForm.targetsAll && !publishForm.filterCompetitionId) {
    try {
      await ElMessageBox.confirm(
        "未选择具体比赛，「本比赛全体」将发送给全部比赛（含其他比赛）的所有账号。确认继续？",
        "确认全站广播",
        { type: "warning", confirmButtonText: "仍要发送", cancelButtonText: "返回选择" },
      );
    } catch {
      return;
    }
  }
  submitting.value = true;
  try {
    await messagesApi.create({
      title: publishForm.title.trim(),
      content: publishForm.content.trim(),
      targetsAll: publishForm.targetsAll,
      targetUserIds: publishForm.targetUserIds,
      // 已预上传的图片元信息（url/filename）随消息一并持久化；落盘文件在删除消息时清理。
      images: publishForm.images,
      // 超管经「按比赛筛选」选中的比赛 → 后端据此把「本比赛全体」/显式选人收敛到该比赛；
      // 不选则为全部比赛（全站广播）。归属账号恒以自身比赛为准，此字段被忽略。
      competitionId: publishForm.filterCompetitionId,
    });
    ElMessage.success("消息已发布");
    // 发送确认：发布者本地也滑入一条右侧弹窗，作为「已发送」反馈。
    // （在线接收方会经实时通道各自收到 message:new 弹窗；发布者自身不在收件人列表，需本地补一条。）
    messageStore.pushToast({
      id: Date.now(),
      title: publishForm.title.trim(),
      content: publishForm.content.trim(),
      senderName: "我（已发送）",
      createdAt: new Date().toISOString(),
    });
    publishVisible.value = false;
    if (activeTab.value !== "sent" && canManage.value) {
      activeTab.value = "sent";
    }
    loadSent();
  } catch (e: any) {
    console.error("发布失败:", e);
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    submitting.value = false;
  }
}

function formatTime(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

onMounted(() => {
  loadInbox();
});
</script>

<style scoped>
.message-center {
  width: 100%;
}
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0;
}
.mm-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tab-badge {
  margin-top: -2px;
}
.list-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}
.empty-tip {
  text-align: center;
  color: var(--color-text-tertiary, #9aa1ad);
  padding: 40px 0;
  font-size: 14px;
}
.msg-card {
  position: relative;
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 16px 18px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #e8eaef);
  border-radius: var(--radius, 12px);
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s, transform 0.2s;
}
.msg-card:hover {
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
  border-color: var(--color-primary, #6366f1);
}
.msg-card.sent {
  cursor: default;
}
.read-dot {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-top: 6px;
  background: transparent;
}
.read-dot.on {
  background: var(--color-primary, #6366f1);
  box-shadow: 0 0 0 4px var(--gradient-brand-soft, #eef0ff);
}
.msg-main {
  flex: 1 1 auto;
  min-width: 0;
}
.msg-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
}
.msg-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-text, #1f2330);
}
.msg-sender {
  font-size: 12px;
  color: var(--color-text-tertiary, #9aa1ad);
}
.msg-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-tertiary, #9aa1ad);
  white-space: nowrap;
}
.msg-content {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--color-text-secondary, #51586a);
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-meta {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.unread-tag {
  flex: 0 0 auto;
}
.del-btn {
  flex: 0 0 auto;
}
.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--color-text-tertiary, #9aa1ad);
}
.img-uploader {
  width: 100%;
}
.img-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}
.img-thumb {
  position: relative;
  width: 84px;
  height: 84px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--color-border, #e8eaef);
}
.img-thumb :deep(.el-image) {
  width: 100%;
  height: 100%;
  display: block;
}
.img-del {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  padding: 0;
  font-size: 12px;
  opacity: 0.92;
}
.img-add {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 84px;
  height: 84px;
  border: 1px dashed var(--color-border, #cdd2dc);
  border-radius: 10px;
  color: var(--color-text-tertiary, #9aa1ad);
  cursor: pointer;
  font-size: 22px;
  transition: border-color 0.2s, color 0.2s;
}
.img-add:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}
.img-add.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.msg-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.msg-img {
  width: 96px;
  height: 96px;
  border-radius: 10px;
  border: 1px solid var(--color-border, #e8eaef);
  overflow: hidden;
  cursor: zoom-in;
}
</style>
