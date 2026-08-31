# Frontend · Vue 3 + TS + Element Plus

## 快速启动

```bash
cd GipfelBusinessCompetitionManagerWeb/frontend

npm install          # 安装依赖（推荐 Node 20 LTS）
npm run dev          # Vite 开发服务器 :5173
# → 自动代理 /api、/socket.io、/uploads 到 http://127.0.0.1:8000
# → 浏览器访问 http://localhost:5173
```

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 开发模式（Vite HMR） |
| `npm run build` | 生产构建 → `dist/`（先 typecheck，再 vite build） |
| `npm run preview` | 本地预览生产构建产物 |
| `npm run typecheck` | 仅 `vue-tsc --noEmit`，CI 必跑 |

## 目录速查

```
src/
├── main.ts                 入口：创建 App、注册 router/pinia/ElementPlus/globalProperties
├── App.vue
├── styles/index.scss       全局样式 + Element Plus 主题变量覆盖
├── layouts/AppLayout.vue   顶栏 + 侧边栏 + <router-view>；所有登录后视图挂在这里
├── router/index.ts         路由表：按角色守卫（meta.requiredRank / requiredPermission）
├── stores/
│   ├── auth.ts             token、user、permissions_list、can/canAny/isSuperAdmin/canAuditCompany
│   ├── competition.ts      比赛列表、currentCompetitionId、fiscalYears、旧API兼容别名（setActiveFiscalYear 等）
│   └── config.ts           消息中心、应用配置
├── api/
│   ├── index.ts            axios 实例（baseURL=/api）+ 所有业务接口（与原 NestJS 路由签名一致）
│   └── types.ts            业务类型（Company/Material/Part/...），同步后端序列化 camelCase 契约
├── utils/
│   ├── permissions/        31 权限键 / 角色动作等级继承表 / has_permission / can()
│   ├── case.ts             toCamel/toSnake 工具
│   └── constants.ts        枚举
├── realtime/
│   ├── socket.ts           Socket.IO 客户端（auth:token、autoConnect=false、连接失败与重连策略）
│   ├── useResourceChanged  响应式广播 composable：按 resource/action/recordId 订阅，自动去重与重放
│   └── resource-changed.ts 类型定义（ResourceChangedEvent）+ diff 辅助
├── contracts/              合同表达式引擎（条件图、效果图）+ useCompetitionReload/useGraphViewport
├── components/
│   ├── common/DataManager  通用 CRUD 组件（materials/fuels/infrastructures 等简单资源直接复用）
│   └── contracts/          合同表达式编辑器（条件/效果、OP、INPUT、字典等）
└── views/
    ├── LoginView.vue       登录 + 改密拦截（auth.required）
    ├── DashboardView.vue   比赛总览
    ├── DataManagerView.vue 数据管理：按比赛域过滤的各资源列表
    ├── MapsView.vue        地图可视化 + 节点编辑
    ├── TechTreeView.vue    科技树
    ├── CompaniesView.vue   公司列表 + 公司字段面板（乐观锁）
    ├── ContractsView.vue   合同模板/合同实例 + 执行/撤销
    ├── StocksView.vue      股票行情 / K 线 / 下单 / 推进轮次
    ├── AccountsView.vue    用户与权限（SUPER_ADMIN 可见）
    └── MessagesView.vue    消息中心（收件箱 + 发布公告）
```

## 与后端的接口契约

完整「每个路由 → 方法 → 参数 → 返回 → 权限键」表见上一层 [Vue-Django迁移设计.md](../Vue-Django迁移设计.md#9.1 前端 API 契约)。

全部 REST 调用走 `src/api/index.ts`：
- axios 实例 baseURL=`/api`，`Authorization: Bearer <token>` 自动注入
- 401 时清除 auth 并 `router.push('/login')`
- 所有错误走统一 `catchError` 弹出 Element Plus `ElMessage.error`
- 成功/失败返回统一信封 `{ ok, message, data, error }`

## 实时广播（Socket.IO）

前端不直接 `socket.on("resource:changed")`，而是用 composable：

```ts
import { useResourceChanged } from "@/realtime/useResourceChanged";

const { records } = useResourceChanged(
  "materials",      // resource
  { competitionId: route.query.competitionId as string },
  { debounceMs: 250, autoReplayOnMount: true },
);

// records.value 自动累积：created 追加、updated 合并、deleted 删除、bulk 全量刷新
// 同时自动执行 sync:replay(lastReceivedSeq) 把断连期间事件补齐
```

## 权限检查（UI 与守卫一致）

```vue
<template>
  <!-- 按钮级 -->
  <el-button v-if="can('edit', 'data:part')">新增零件</el-button>
  <!-- 只要任一满足 -->
  <el-button v-if="canAny(['manage','edit'], ['account','competition'])">导出</el-button>
</template>

<script setup lang="ts">
import { useAuthStore } from "@/stores/auth";
const auth = useAuthStore();
const { can, canAny } = auth;
</script>
```

路由级守卫：`router/index.ts` 的 `meta.requiredRank` 与 `meta.requiredPermission`。

## 生产构建

```bash
npm ci && npm run build    # 可重复构建（CI 推荐 ci 替代 install）
# 产物 → dist/
#   index.html
#   assets/index-[hash].js
#   assets/index-[hash].css
#   图片/字体等资源

# 部署建议：直接把 dist/ 作为 nginx root，/api /socket.io 反向代理到 Django 8000
```

## 开发代理配置

Vite dev 已在 `vite.config.ts` 中设置：

```
/api/*        → http://127.0.0.1:8000
/socket.io/*  → http://127.0.0.1:8000  (ws: true)
/uploads/*    → http://127.0.0.1:8000
```

生产部署改 nginx 的 `location` 块写同样三条规则即可（见 `../deploy/nginx-gipfel.conf`）。
