/* 日志查看器前端：Vue3 + Element Plus（与业务前端同一套组件库，风格一致） */
(function () {
  const { createApp } = Vue;
  const EP = ElementPlus;
  const ElMessage = EP.ElMessage;
  const locale = window.ElementPlusLocaleZhCn || null;

  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[2]) : "";
  }

  function fmtSize(bytes) {
    if (!bytes && bytes !== 0) return "-";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(2) + " MB";
  }

  async function api(url, options) {
    options = options || {};
    options.credentials = "include";
    options.headers = options.headers || {};
    if (options.body && !options.headers["Content-Type"]) {
      options.headers["Content-Type"] = "application/json";
    }
    if ((options.method || "GET").toUpperCase() !== "GET") {
      options.headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    const resp = await fetch(url, options);
    let data = null;
    try {
      data = await resp.json();
    } catch (e) {
      data = null;
    }
    if (!resp.ok) {
      const err = new Error((data && data.message) || "请求失败");
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  const TEMPLATE = `
  <div class="login-wrap" v-if="!authenticated">
    <div class="login-card">
      <div class="login-title">日志查看器</div>
      <div class="login-sub">Gipfel 商赛系统 · 运维后台</div>
      <el-form label-position="top" @submit.prevent="doLogin">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名"
            @keyup.enter="doLogin" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password
            placeholder="请输入密码" @keyup.enter="doLogin" />
        </el-form-item>
        <el-alert v-if="loginError" :title="loginError" type="error" show-icon
          :closable="false" style="margin-bottom:12px" />
        <el-button type="primary" :loading="logging" style="width:100%"
          @click="doLogin">登 录</el-button>
      </el-form>
    </div>
  </div>

  <template v-else>
    <div class="app-header">
      <div class="brand">📋 日志查看器</div>
      <div class="spacer"></div>
      <span class="user">当前：{{ username }}</span>
      <el-button size="small" @click="doLogout">退出登录</el-button>
    </div>

    <div class="toolbar">
      <el-select v-model="currentFile" style="width:240px" placeholder="选择日志文件"
        @change="onFileChange">
        <el-option v-for="f in files" :key="f.name"
          :label="f.name + '  (' + fmtSize(f.size) + ')'" :value="f.name" />
      </el-select>
      <el-select v-model="level" style="width:130px" @change="loadLogs">
        <el-option label="全部级别" value="ALL" />
        <el-option label="INFO" value="INFO" />
        <el-option label="WARN" value="WARN" />
        <el-option label="ERROR" value="ERROR" />
        <el-option label="DEBUG" value="DEBUG" />
      </el-select>
      <el-input v-model="search" class="grow" clearable
        placeholder="关键字过滤（消息 / 记录器 / 操作人）"
        @keyup.enter="loadLogs" @clear="loadLogs">
        <template #append>
          <el-button @click="loadLogs">查询</el-button>
        </template>
      </el-input>
      <el-switch v-model="autoRefresh" active-text="实时跟随" @change="onAutoChange" />
      <el-button type="primary" :loading="loading" @click="loadLogs">刷新</el-button>
    </div>

    <div class="log-body">
      <div class="log-meta">
        文件：{{ currentFile }} ｜ 命中 <b>{{ total }}</b> 行 ｜ 大小 {{ fmtSize(fileSize) }}
        <span v-if="truncated" style="color:#e6a23c">（文件过大，仅显示尾部）</span>
      </div>
      <div class="log-table-wrap">
        <el-table :data="rows" height="100%" stripe size="small" style="width:100%">
          <el-table-column type="index" label="#" width="56" />
          <el-table-column prop="time" label="时间" width="185" />
          <el-table-column label="级别" width="86">
            <template #default="{ row }">
              <span :class="'lv-' + row.level" style="font-weight:600">{{ row.level || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="logger" label="记录器" width="210" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作人" width="150" show-overflow-tooltip />
          <el-table-column label="消息">
            <template #default="{ row }">
              <div class="msg-cell">{{ row.message }}</div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </template>
  `;

  const app = createApp({
    template: TEMPLATE,
    data() {
      return {
        authenticated: false,
        username: "",
        form: { username: "", password: "" },
        logging: false,
        loginError: "",
        files: [],
        currentFile: "",
        level: "ALL",
        search: "",
        rows: [],
        total: 0,
        fileSize: 0,
        truncated: false,
        loading: false,
        autoRefresh: true,
        _timer: null,
      };
    },
    methods: {
      fmtSize,
      async whoami() {
        try {
          const d = await api("/api/auth/whoami");
          this.authenticated = !!d.authenticated;
          this.username = d.username || "";
        } catch (e) {
          this.authenticated = false;
        }
      },
      async doLogin() {
        this.logging = true;
        this.loginError = "";
        try {
          const d = await api("/api/auth/login", {
            method: "POST",
            body: JSON.stringify(this.form),
          });
          if (d.ok) {
            this.authenticated = true;
            this.username = d.username;
            this.form.password = "";
            await this.loadFiles();
            await this.loadLogs();
            this.startPolling();
          }
        } catch (e) {
          this.loginError = e.message || "登录失败";
        } finally {
          this.logging = false;
        }
      },
      async doLogout() {
        try {
          await api("/api/auth/logout", { method: "POST" });
        } catch (e) {}
        this.stopPolling();
        this.authenticated = false;
        this.username = "";
        this.rows = [];
        this.files = [];
      },
      async loadFiles() {
        try {
          const d = await api("/api/logs/files");
          this.files = d.files || [];
          if (!this.currentFile && this.files.length) {
            this.currentFile = this.files[0].name;
          }
        } catch (e) {
          ElMessage.error("加载日志文件列表失败：" + e.message);
        }
      },
      async loadLogs() {
        if (!this.currentFile) return;
        this.loading = true;
        try {
          const params = new URLSearchParams({
            file: this.currentFile,
            mode: "tail",
            lines: "300",
            level: this.level,
            q: this.search,
          });
          const d = await api("/api/logs?" + params.toString());
          this.rows = d.rows || [];
          this.total = d.total || 0;
          this.fileSize = d.size || 0;
          this.truncated = !!d.truncated;
        } catch (e) {
          if (e.status === 401) {
            this.authenticated = false;
            this.stopPolling();
          } else {
            ElMessage.error("加载日志失败：" + e.message);
          }
        } finally {
          this.loading = false;
        }
      },
      onFileChange() {
        this.loadLogs();
      },
      onAutoChange(val) {
        if (val) this.startPolling();
        else this.stopPolling();
      },
      startPolling() {
        this.stopPolling();
        this._timer = setInterval(() => {
          if (this.authenticated) this.loadLogs();
        }, 2000);
      },
      stopPolling() {
        if (this._timer) {
          clearInterval(this._timer);
          this._timer = null;
        }
      },
    },
    async mounted() {
      await this.whoami();
      if (this.authenticated) {
        await this.loadFiles();
        await this.loadLogs();
        if (this.autoRefresh) this.startPolling();
      }
    },
    beforeUnmount() {
      this.stopPolling();
    },
  });

  if (locale) app.use(EP, { locale });
  else app.use(EP);
  app.mount("#app");
})();
