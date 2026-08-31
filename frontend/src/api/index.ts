/**
 * API 调用封装（按模块聚合）。
 * 保持与原 NestJS 路由前缀一致：/api/<resource>。
 *
 * 兼容两套视图：
 *  - 重写后的简单视图经 DataManager 使用 createCrud（.list(params)/.get/.create/.update/.delete）
 *  - 移植自原客户端的复杂视图使用富 API（.list(enabledOnly)/.remove/.updatePartyNumbers 等）
 *    故富 API 同时提供 .remove 与 .delete 别名、PATCH 版 .update。
 */
import api from "./request";
import type { ApiInstance } from "./request";

export { getErrorMessage } from "./request";

export interface PageParams {
  page?: number;
  pageSize?: number;
  updatedAfter?: string;
  requireExistingIds?: string | "true";
  /** competitionId：数字或 "null"（查询未归属比赛的系统账号） */
  competitionId?: number | string;
}

export interface PagedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

const http = api as ApiInstance;

// ==================== Auth ====================
// 与 stores/auth.ts 约定：login(username, password)、me()、changePassword(old, new)
export const authApi = {
  login: (username: string, password: string) =>
    http.post("/auth/login", { username, password }),
  me: () => http.get("/auth/me"),
  changePassword: (oldPassword: string, newPassword: string) =>
    http.post("/auth/change-password", { oldPassword, newPassword }),
};

// ==================== Users ====================
export const usersApi = {
  list: (params: PageParams = {}) => http.get("/users", { params }),
  get: (id: number) => http.get(`/users/${id}`),
  create: (data: Record<string, unknown>) => http.post("/users", data),
  update: (id: number, data: Record<string, unknown>) => http.patch(`/users/${id}`, data),
  updatePassword: (id: number, data: { password: string }) =>
    http.patch(`/users/${id}/password`, data),
  remove: (id: number) => http.delete(`/users/${id}`),
  delete: (id: number) => http.delete(`/users/${id}`),
  grantPermissions: (id: number, data: Record<string, unknown>) =>
    http.post(`/users/${id}/permissions`, data),
};

// ==================== Competitions ====================
export const competitionsApi = {
  list: () => http.get("/competitions"),
  get: (id: number) => http.get(`/competitions/${id}`),
  create: (data: Record<string, unknown>) => http.post("/competitions", data),
  update: (id: number, data: Record<string, unknown>) => http.patch(`/competitions/${id}`, data),
  delete: (id: number) => http.delete(`/competitions/${id}`),
  fiscalYears: {
    list: (competitionId: number) =>
      http.get(`/competitions/${competitionId}/fiscal-years`),
    create: (competitionId: number, year: number) =>
      http.post(`/competitions/${competitionId}/fiscal-years`, { year }),
    update: (id: number, data: Record<string, unknown>) =>
      http.patch(`/competitions/fiscal-years/${id}`, data),
    delete: (id: number) => http.delete(`/competitions/fiscal-years/${id}`),
  },
};

// ==================== 通用资源工厂 ====================
/** 生成标准 CRUD API。.delete 与 .remove 同义，.update 用 PUT（DataManager）。 */
export function createCrud<T = any>(prefix: string) {
  return {
    list: (params: PageParams = {}) => http.get<T[] | PagedResponse<T>>(prefix, { params }),
    get: (id: number) => http.get<T>(`${prefix}/${id}`),
    create: (data: Partial<T>) => http.post<T>(prefix, data),
    update: (id: number, data: Partial<T>) => http.put<T>(`${prefix}/${id}`, data),
    patch: (id: number, data: Partial<T>) => http.patch<T>(`${prefix}/${id}`, data),
    delete: (id: number) => http.delete(`${prefix}/${id}`),
    remove: (id: number) => http.delete(`${prefix}/${id}`),
  };
}

// 生产链主数据（DataManager 使用 createCrud）
export const materialsApi = createCrud("/materials");
export const partsApi = createCrud("/parts");
export const productsApi = createCrud("/products");
export const techNodesApi = createCrud("/tech-nodes");
export const infrastructuresApi = createCrud("/infrastructures");
export const fuelsApi = createCrud("/fuels");
export const vehiclesApi = createCrud("/vehicles");
export const warehousesApi = createCrud("/warehouses");
export const productionLinesApi = createCrud("/production-lines");

// ==================== 地图 ====================
export const mapsApi = {
  // 兼容两种调用：full(competitionId) 或 full({competitionId})
  full: (arg?: number | { competitionId?: number }, params: PageParams = {}) => {
    const competitionId =
      typeof arg === "number" ? arg : arg?.competitionId;
    return http.get("/maps/full", { params: { competitionId, ...params } });
  },
  nodeTypes: {
    list: (competitionId?: number) =>
      http.get("/map-node-types", { params: competitionId != null ? { competitionId } : {} }),
    create: (data: any) => http.post("/map-node-types", data),
    update: (id: number, data: any) => http.patch(`/map-node-types/${id}`, data),
    remove: (id: number) => http.delete(`/map-node-types/${id}`),
    delete: (id: number) => http.delete(`/map-node-types/${id}`),
  },
  pathTypes: {
    list: (competitionId?: number) =>
      http.get("/path-types", { params: competitionId != null ? { competitionId } : {} }),
    create: (data: any) => http.post("/path-types", data),
    update: (id: number, data: any) => http.patch(`/path-types/${id}`, data),
    remove: (id: number) => http.delete(`/path-types/${id}`),
    delete: (id: number) => http.delete(`/path-types/${id}`),
  },
  nodes: {
    list: (page = 1, pageSize = 100, competitionId?: number) => {
      const params: Record<string, unknown> = { page, pageSize };
      if (competitionId != null) params.competitionId = competitionId;
      return http.get("/map-nodes", { params });
    },
    create: (data: any) => http.post("/map-nodes", data),
    update: (id: number, data: any) => http.patch(`/map-nodes/${id}`, data),
    remove: (id: number) => http.delete(`/map-nodes/${id}`),
    delete: (id: number) => http.delete(`/map-nodes/${id}`),
  },
  edges: {
    list: (page = 1, pageSize = 200, competitionId?: number) => {
      const params: Record<string, unknown> = { page, pageSize };
      if (competitionId != null) params.competitionId = competitionId;
      return http.get("/map-edges", { params });
    },
    create: (data: any) => http.post("/map-edges", data),
    update: (id: number, data: any) => http.patch(`/map-edges/${id}`, data),
    remove: (id: number) => http.delete(`/map-edges/${id}`),
    delete: (id: number) => http.delete(`/map-edges/${id}`),
  },
  mapBackground: {
    upload: (file: File, competitionId?: number) => {
      const fd = new FormData();
      fd.append("file", file);
      if (competitionId != null) fd.append("competitionId", String(competitionId));
      return http.post("/files/map-background", fd);
    },
    remove: (competitionId?: number) =>
      http.delete("/files/map-background", competitionId != null ? { data: { competitionId } } : undefined),
    get: (competitionId?: number) =>
      http.get("/files/map-background", { params: competitionId != null ? { competitionId } : {} }),
    updateTransform: (transform: { x: number; y: number; scale: number }, competitionId?: number) => {
      const data: any = { ...transform };
      if (competitionId != null) data.competitionId = competitionId;
      return http.patch("/files/map-background/transform", data);
    },
  },
};

// ==================== 产业系统 ====================
export const industryTypesApi = {
  list: () => http.get("/industry-types"),
  get: (id: number) => http.get(`/industry-types/${id}`),
  create: (data: any) => http.post("/industry-types", data),
  update: (id: number, data: any) => http.patch(`/industry-types/${id}`, data),
  remove: (id: number) => http.delete(`/industry-types/${id}`),
  delete: (id: number) => http.delete(`/industry-types/${id}`),
  listFields: (id: number) => http.get(`/industry-types/${id}/fields`),
  createField: (id: number, data: any) => http.post(`/industry-types/${id}/fields`, data),
  updateField: (fieldId: number, data: any) =>
    http.patch(`/industry-types/fields/${fieldId}`, data),
  removeField: (fieldId: number) => http.delete(`/industry-types/fields/${fieldId}`),
};

export const industryFieldsApi = createCrud("/industry-fields");

export const companyFieldsApi = {
  get: (companyId: number, opts?: { includeHidden?: boolean }) =>
    http.get(
      `/company-fields/${companyId}`,
      opts?.includeHidden ? { params: { includeHidden: true } } : undefined,
    ),
  set: (
    companyId: number,
    data: {
      industryTypeId?: number;
      fields: { industryFieldId: number; value: string }[];
    },
  ) => http.put(`/company-fields/${companyId}`, data),
  setField: (companyId: number, fieldId: number, data: { value: string; version?: number }) =>
    http.put(`/company-fields/${companyId}/${fieldId}`, data),
};

export const companiesApi = {
  list: (params?: { competitionId?: number; regionId?: number }) =>
    http.get("/companies", { params: params || {} }),
  get: (id: number) => http.get(`/companies/${id}`),
  create: (data: any) => http.post("/companies", data),
  update: (id: number, data: any) => http.patch(`/companies/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    http.delete(`/companies/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  delete: (id: number) => http.delete(`/companies/${id}`),
  fields: (companyId: number) => http.get(`/company-fields/${companyId}`),
};

export const regionsApi = {
  list: (params: PageParams = {}) => http.get("/regions", { params }),
  create: (data: any) => http.post("/regions", data),
  remove: (id: number, competitionId?: number | null) =>
    http.delete(`/regions/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  delete: (id: number) => http.delete(`/regions/${id}`),
  mapOverview: (competitionId?: number) =>
    http.get("/regions/map-overview", { params: competitionId != null ? { competitionId } : {} }),
  saveOverviewCardsByName: (
    name: string,
    cards: { id?: string; displayName: string; companyId: number; industryFieldId: number }[],
    competitionId?: number,
  ) =>
    http.put(
      `/regions/by-name/${encodeURIComponent(name)}/overview-cards`,
      { cards },
      { params: competitionId != null ? { competitionId } : {} },
    ),
};

export const consumerDemandsApi = {
  list: (competitionId?: number, region?: string) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    if (region != null) params.region = region;
    return http.get("/consumer-demands", { params });
  },
  create: (data: any) => http.post("/consumer-demands", data),
  update: (id: number, data: any) => http.patch(`/consumer-demands/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    http.delete(`/consumer-demands/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  delete: (id: number) => http.delete(`/consumer-demands/${id}`),
};

// ==================== 合同 ====================
export const contractTypesApi = {
  list: (enabledOnly: boolean | PageParams = false) =>
    http.get("/contract-types", {
      params: typeof enabledOnly === "boolean" ? { enabledOnly } : enabledOnly,
    }),
  get: (id: number) => http.get(`/contract-types/${id}`),
  create: (data: any) => http.post("/contract-types", data),
  update: (id: number, data: any) => http.patch(`/contract-types/${id}`, data),
  remove: (id: number) => http.delete(`/contract-types/${id}`),
  delete: (id: number) => http.delete(`/contract-types/${id}`),
};

export const contractsApi = {
  list: (params?: { competitionId?: number; status?: string; page?: number; pageSize?: number }) =>
    http.get("/contracts", { params: params || {} }),
  get: (id: number) => http.get(`/contracts/${id}`),
  create: (data: any) => http.post("/contracts", data),
  update: (id: number, data: any) => http.patch(`/contracts/${id}`, data),
  execute: (id: number, data?: Record<string, unknown>) =>
    http.post(`/contracts/${id}/execute`, data || {}),
  trial: (id: number, data: Record<string, unknown>) =>
    http.post(`/contracts/${id}/trial`, data),
  updatePartyNumbers: (id: number, partyNumbers: Record<string, string>) =>
    http.patch(`/contracts/${id}/party-numbers`, { partyNumbers }),
  precheck: (id: number) => http.post(`/contracts/${id}/precheck`),
  setStatus: (id: number, status: string) =>
    http.patch(`/contracts/${id}/status`, { status }),
  remove: (id: number, competitionId?: number | null) =>
    http.delete(`/contracts/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  delete: (id: number) => http.delete(`/contracts/${id}`),
};

// ==================== 消息 ====================
export interface MessageImage {
  /** 相对服务端根的路径，形如 /uploads/message-images/xxx.png */
  url: string;
  /** 落盘文件名（删除消息时由服务端清理）。 */
  filename: string;
}

/** 消息主体（与后端 Message 模型对应）。 */
export interface MessageItem {
  id: number;
  title: string;
  content: string;
  senderId: number;
  competitionId: number | null;
  targetsAll: boolean;
  targetUserIds: number[];
  /** 消息附带图片元信息列表。 */
  images: MessageImage[] | null;
  createdAt: string;
  updatedAt: string;
}

/** 收件箱条目：当前用户维度的一条收信记录。 */
export interface InboxItem {
  recipientId: number;
  read: boolean;
  readAt: string | null;
  message: MessageItem;
  senderName: string;
}

/** 已发布消息条目：发布者维度的一条发送记录。 */
export interface SentItem extends MessageItem {
  _count: { recipients: number };
  senderName: string;
}

export const messagesApi = {
  list: (params: PageParams = {}) => http.get("/messages", { params }),
  inbox: (params: PageParams = {}) => http.get("/messages/inbox", { params }),
  sent: () => http.get("/messages/sent"),
  get: (id: number) => http.get(`/messages/${id}`),
  create: (data: any) => http.post("/messages", data),
  delete: (id: number) => http.delete(`/messages/${id}`),
  remove: (id: number) => http.delete(`/messages/${id}`),
  markRead: (id: number) => http.patch(`/messages/${id}/read`),
  markAllRead: () => http.post("/messages/read-all"),
  unreadCount: () => http.get("/messages/unread-count"),
  selectableUsers: (competitionId?: number) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    return http.get("/messages/selectable-users", { params });
  },
  uploadImage: (file: File): Promise<MessageImage> => {
    const fd = new FormData();
    fd.append("file", file);
    return http.post("/messages/upload-image", fd);
  },
};

// ==================== 股票 ====================
export const stockApi = {
  list: (page = 1, pageSize = 100, competitionId?: number) => {
    const params: Record<string, unknown> = { page, pageSize };
    if (competitionId != null) params.competitionId = competitionId;
    return http.get("/stocks", { params });
  },
  get: (id: number) => http.get(`/stocks/${id}`),
  candles: (id: number) => http.get(`/stocks/${id}/candles`),
  pbSources: (competitionId?: number) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    return http.get("/stocks/pb-sources", { params });
  },
  create: (data: any) => http.post("/stocks", data),
  update: (id: number, data: any) => http.patch(`/stocks/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    http.delete(`/stocks/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  delete: (id: number) => http.delete(`/stocks/${id}`),

  listAccounts: (competitionId: number) => http.get("/stocks/accounts/list", { params: { competitionId } }),
  accountOverview: (competitionId: number) =>
    http.get("/stocks/accounts/overview", { params: { competitionId } }),
  getAccount: (id: number) => http.get(`/stocks/accounts/${id}`),
  accountHoldings: (id: number) => http.get(`/stocks/accounts/${id}/holdings`),
  createAccount: (data: any) => http.post("/stocks/accounts", data),
  updateAccount: (id: number, data: any) => http.patch(`/stocks/accounts/${id}`, data),
  removeAccount: (id: number) => http.delete(`/stocks/accounts/${id}`),

  listOrders: (competitionId: number, stockId?: number, fundsAccountId?: number) => {
    const params: Record<string, unknown> = { competitionId };
    if (stockId != null) params.stockId = stockId;
    if (fundsAccountId != null) params.fundsAccountId = fundsAccountId;
    return http.get("/stocks/orders/list", { params });
  },
  placeOrder: (data: any) => http.post("/stocks/orders", data),
  cancelOrder: (id: number) => http.delete(`/stocks/orders/${id}`),

  listHoldings: (competitionId: number, accountId?: number) => {
    const params: Record<string, unknown> = { competitionId };
    if (accountId != null) params.accountId = accountId;
    return http.get("/stocks/holdings/list", { params });
  },

  advanceRound: (
    competitionId: number,
    dto: {
      stockIds?: number[];
      marketMaker?: { enabled?: boolean; spreadPct?: number; levels?: number; baseQuantity?: number };
      stockConfig?: Record<string, unknown>;
    } = {},
  ) => http.post(`/stocks/advance-round?competitionId=${competitionId}`, dto),
};

// 兼容重写版命名（stocksApi 复数 + 子资源）
export const stocksApi = {
  ...createCrud("/stocks"),
  advance: (competitionId: number) => http.post("/stocks/advance", { competitionId }),
};
export const stockAccountsApi = createCrud("/stock-accounts");
export const stockOrdersApi = createCrud("/stock-orders");
export const stockHoldingsApi = createCrud("/stock-holdings");
export const stockCandlesApi = {
  list: (stockId: number) => http.get("/stock-candles", { params: { stockId } }),
};

// ==================== 文件 ====================
export const filesApi = {
  upload: (formData: FormData) =>
    http.post("/files/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    } as any),
};

// ==================== 审计 ====================
export const auditApi = {
  list: (params: PageParams = {}) => http.get("/audit-logs", { params }),
};

export default http;
