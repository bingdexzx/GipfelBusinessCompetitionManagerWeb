import api, { getErrorMessage } from "./request";
import type {
  CreateUserInput,
  UpdateUserInput,
  CreateMaterialInput,
  UpdateMaterialInput,
  CreatePartInput,
  UpdatePartInput,
  CreateProductInput,
  UpdateProductInput,
  CreateMapNodeInput,
  UpdateMapNodeInput,
  CreateMapEdgeInput,
  UpdateMapEdgeInput,
  CreateMapNodeTypeInput,
  UpdateMapNodeTypeInput,
  CreatePathTypeInput,
  UpdatePathTypeInput,
  CreateInfrastructureInput,
  UpdateInfrastructureInput,
  CreateFuelInput,
  UpdateFuelInput,
  CreateIndustryTypeInput,
  UpdateIndustryTypeInput,
  CreateIndustryFieldInput,
  UpdateIndustryFieldInput,
  CreateContractTypeInput,
  UpdateContractTypeInput,
  CreateContractInput,
  UpdateCompanyInput,
  CreateRegionInput,
  CreateStockInput,
  UpdateStockInput,
  CreateStockFundsAccountInput,
  UpdateStockFundsAccountInput,
  CreateStockOrderInput,
} from "@/types/api";

export { getErrorMessage };

// 默认导出底层请求实例（即 request.ts 的默认导出 cachedApi）。
// 心跳等场景需要显式绕过本地缓存层真实打网络（传 cache:false），故直接复用此实例。
export default api;

export const authApi = {
  login: (data: { username: string; password: string }) => api.post("/auth/login", data),
  getProfile: () => api.get("/auth/me"),
  changePassword: (data: { oldPassword: string; newPassword: string }) =>
    api.post("/auth/change-password", data),
};

export const usersApi = {
  list: (params?: { page?: number; pageSize?: number; competitionId?: number | string }) => {
    const query: Record<string, unknown> = {
      page: params?.page ?? 1,
      pageSize: params?.pageSize ?? 20,
    };
    if (params?.competitionId !== undefined) query.competitionId = params.competitionId;
    return api.get("/users", { params: query });
  },
  get: (id: number) => api.get(`/users/${id}`),
  create: (data: CreateUserInput | Record<string, unknown>) => api.post("/users", data),
  update: (id: number, data: UpdateUserInput) => api.patch(`/users/${id}`, data),
  updatePassword: (id: number, data: { password: string }) =>
    api.patch(`/users/${id}/password`, data),
  remove: (id: number) => api.delete(`/users/${id}`),
};

export const materialsApi = {
  list: (page = 1, pageSize = 50) => api.get("/materials", { params: { page, pageSize } }),
  get: (id: number) => api.get(`/materials/${id}`),
  create: (data: CreateMaterialInput) => api.post("/materials", data),
  update: (id: number, data: UpdateMaterialInput) => api.patch(`/materials/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/materials/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/materials/${id}/impact`, { cache: false }),
};

export const partsApi = {
  list: (page = 1, pageSize = 50) => api.get("/parts", { params: { page, pageSize } }),
  get: (id: number) => api.get(`/parts/${id}`),
  create: (data: CreatePartInput) => api.post("/parts", data),
  update: (id: number, data: UpdatePartInput) => api.patch(`/parts/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/parts/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/parts/${id}/impact`, { cache: false }),
};

export const productsApi = {
  list: (page = 1, pageSize = 50) => api.get("/products", { params: { page, pageSize } }),
  get: (id: number) => api.get(`/products/${id}`),
  create: (data: CreateProductInput) => api.post("/products", data),
  update: (id: number, data: UpdateProductInput) => api.patch(`/products/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/products/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/products/${id}/impact`, { cache: false }),
};

export const mapsApi = {
  full: (params?: { competitionId?: number }) => api.get("/maps/full", { params }),
  nodes: {
    list: (page = 1, pageSize = 100, competitionId?: number) => {
      const params: Record<string, unknown> = { page, pageSize };
      if (competitionId != null) params.competitionId = competitionId;
      return api.get("/map-nodes", { params });
    },
    create: (data: CreateMapNodeInput) => api.post("/map-nodes", data),
    update: (id: number, data: UpdateMapNodeInput) => api.patch(`/map-nodes/${id}`, data),
    remove: (id: number, competitionId?: number | null) =>
      api.delete(`/map-nodes/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
    impact: (id: number) => api.get(`/map-nodes/${id}/impact`, { cache: false }),
  },
  edges: {
    list: (page = 1, pageSize = 200, competitionId?: number) => {
      const params: Record<string, unknown> = { page, pageSize };
      if (competitionId != null) params.competitionId = competitionId;
      return api.get("/map-edges", { params });
    },
    create: (data: CreateMapEdgeInput) => api.post("/map-edges", data),
    update: (id: number, data: UpdateMapEdgeInput) => api.patch(`/map-edges/${id}`, data),
    remove: (id: number, competitionId?: number | null) =>
      api.delete(`/map-edges/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
    impact: (id: number) => api.get(`/map-edges/${id}/impact`, { cache: false }),
  },
  nodeTypes: {
    list: (competitionId?: number) => {
      const params: Record<string, unknown> = {};
      if (competitionId != null) params.competitionId = competitionId;
      return api.get("/map-node-types", { params });
    },
    create: (data: CreateMapNodeTypeInput) => api.post("/map-node-types", data),
    update: (id: number, data: UpdateMapNodeTypeInput) => api.patch(`/map-node-types/${id}`, data),
    remove: (id: number, competitionId?: number | null) =>
      api.delete(`/map-node-types/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
    impact: (id: number) => api.get(`/map-node-types/${id}/impact`, { cache: false }),
  },
  pathTypes: {
    list: (competitionId?: number) => {
      const params: Record<string, unknown> = {};
      if (competitionId != null) params.competitionId = competitionId;
      return api.get("/path-types", { params });
    },
    create: (data: CreatePathTypeInput) => api.post("/path-types", data),
    update: (id: number, data: UpdatePathTypeInput) => api.patch(`/path-types/${id}`, data),
    remove: (id: number, competitionId?: number | null) =>
      api.delete(`/path-types/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
    impact: (id: number) => api.get(`/path-types/${id}/impact`, { cache: false }),
  },
  // 地图背景图：每比赛一张，由管理端上传，作为整张地图编辑器的背景图层（不影响节点/边坐标）。
  // 端点经 @NoCompetitionScope：归属比赛由服务端按角色强制收敛（超管指定 competitionId，归属账号仅限自身比赛）。
  mapBackground: {
    // 上传：multipart/form-data，字段名 "file"；归属账号无需传 competitionId（服务端强制自身比赛）。
    upload: (file: File, competitionId?: number) => {
      const fd = new FormData();
      fd.append("file", file);
      if (competitionId != null) fd.append("competitionId", String(competitionId));
      return api.post("/files/map-background", fd);
    },
    // 删除：DELETE 带 body（axios 经 config.data 发送），成功后背景立即清空。
    remove: (competitionId?: number) =>
      api.delete(
        "/files/map-background",
        competitionId != null ? { data: { competitionId } } : undefined,
      ),
    // 查看：仅 JwtAuthGuard，返回 BackgroundMeta | null（meta.url 为 /uploads/... 相对路径，前端拼接 baseURL）。
    get: (competitionId?: number) =>
      api.get(
        "/files/map-background",
        competitionId != null
          ? { params: { competitionId }, cache: false }
          : { cache: false },
      ),
    // 更新变换（位置 + 缩放）：PATCH /files/map-background/transform，需 data:map:edit。
    // transform 为 { x, y, scale }（世界坐标）；归属账号无需传 competitionId。
    updateTransform: (
      transform: { x: number; y: number; scale: number },
      competitionId?: number,
    ) => {
      const data: { x: number; y: number; scale: number; competitionId?: number } = { ...transform };
      if (competitionId != null) data.competitionId = competitionId;
      return api.patch("/files/map-background/transform", data);
    },
  },
};

export const infrastructuresApi = {
  list: (params?: { competitionId?: number; page?: number; pageSize?: number }) =>
    api.get("/infrastructures", { params: params || {} }),
  get: (id: number) => api.get(`/infrastructures/${id}`),
  create: (data: CreateInfrastructureInput) => api.post("/infrastructures", data),
  update: (id: number, data: UpdateInfrastructureInput) => api.patch(`/infrastructures/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/infrastructures/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/infrastructures/${id}/impact`, { cache: false }),
};

export const fuelsApi = {
  list: (params?: { competitionId?: number; page?: number; pageSize?: number }) =>
    api.get("/fuels", { params: params || {} }),
  get: (id: number) => api.get(`/fuels/${id}`),
  create: (data: CreateFuelInput) => api.post("/fuels", data),
  update: (id: number, data: UpdateFuelInput) => api.patch(`/fuels/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/fuels/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/fuels/${id}/impact`, { cache: false }),
};

export const industryTypesApi = {
  list: () => api.get("/industry-types"),
  get: (id: number) => api.get(`/industry-types/${id}`),
  create: (data: CreateIndustryTypeInput) => api.post("/industry-types", data),
  update: (id: number, data: UpdateIndustryTypeInput) => api.patch(`/industry-types/${id}`, data),
  remove: (id: number) => api.delete(`/industry-types/${id}`),
  listFields: (id: number) => api.get(`/industry-types/${id}/fields`),
  createField: (id: number, data: CreateIndustryFieldInput) => api.post(`/industry-types/${id}/fields`, data),
  updateField: (fieldId: number, data: UpdateIndustryFieldInput) => api.patch(`/industry-types/fields/${fieldId}`, data),
  removeField: (fieldId: number) => api.delete(`/industry-types/fields/${fieldId}`),
};

export const companyFieldsApi = {
  // 读取某公司产业字段当前值
  get: (companyId: number, opts?: { includeHidden?: boolean }) =>
    api.get(
      `/company-fields/${companyId}`,
      opts?.includeHidden ? { params: { includeHidden: true } } : undefined,
    ),
  // 批量写入某公司产业字段值
  set: (companyId: number, data: { industryTypeId?: number; fields: { industryFieldId: number; value: string }[] }) =>
    api.put(`/company-fields/${companyId}`, data),
};

export const contractTypesApi = {
  list: (enabledOnly = false) => api.get("/contract-types", { params: { enabledOnly } }),
  get: (id: number) => api.get(`/contract-types/${id}`),
  create: (data: CreateContractTypeInput) => api.post("/contract-types", data),
  update: (id: number, data: UpdateContractTypeInput) => api.patch(`/contract-types/${id}`, data),
  remove: (id: number) => api.delete(`/contract-types/${id}`),
};

export const contractsApi = {
  list: (params?: { competitionId?: number; status?: string; page?: number; pageSize?: number }) =>
    api.get("/contracts", { params: params || {} }),
  get: (id: number) => api.get(`/contracts/${id}`),
  create: (data: CreateContractInput) => api.post("/contracts", data),
  execute: (id: number, data?: Record<string, unknown>) => api.post(`/contracts/${id}/execute`, data || {}),
  // 分步补全合同编号：传入 { [role]: 编号 }，仅更新指定参与方
  updatePartyNumbers: (id: number, partyNumbers: Record<string, string>) =>
    api.patch(`/contracts/${id}/party-numbers`, { partyNumbers }),
  precheck: (id: number) => api.post(`/contracts/${id}/precheck`),
  setStatus: (id: number, status: string) => api.patch(`/contracts/${id}/status`, { status }),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/contracts/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/contracts/${id}/impact`, { cache: false }),
};

export const companiesApi = {
  // 列出公司（可按比赛 / 区域过滤）。权限编辑器中用于选择「合同审核范围」；区域管理用于按区域枚举公司。
  list: (params?: { competitionId?: number; regionId?: number }) =>
    api.get("/companies", { params: params || {} }),
  get: (id: number) => api.get(`/companies/${id}`),
  update: (id: number, data: UpdateCompanyInput) => api.patch(`/companies/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/companies/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  impact: (id: number) => api.get(`/companies/${id}/impact`, { cache: false }),
};

export const regionsApi = {
  create: (data: CreateRegionInput) => api.post("/regions", data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/regions/${id}`, competitionId != null ? { params: { competitionId } } : undefined),
  // 地图区域总览：区域来自地图节点去重，返回 [{ region, companies, cards }]（读，绕过集合缓存）
  mapOverview: (competitionId?: number) =>
    api.get("/regions/map-overview", {
      params: competitionId != null ? { competitionId } : {},
      cache: false,
    }),
  // 按区域名保存总览卡片配置（find-or-create，覆盖写）
  saveOverviewCardsByName: (name: string, cards: { id?: string; displayName: string; companyId: number; industryFieldId: number }[], competitionId?: number) =>
    api.put(
      `/regions/by-name/${encodeURIComponent(name)}/overview-cards`,
      { cards },
      { params: competitionId != null ? { competitionId } : {} },
    ),
};

export const consumerDemandsApi = {
  // 列出某比赛的消费者需求（可选按区域过滤）
  list: (competitionId?: number, region?: string) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    if (region != null) params.region = region;
    return api.get("/consumer-demands", { params, cache: false });
  },
  create: (data: { competitionId?: number; region: string; productId: number; quantity?: number; note?: string }) =>
    api.post("/consumer-demands", data),
  update: (id: number, data: { region?: string; productType?: string; quantity?: number; note?: string }) =>
    api.patch(`/consumer-demands/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(
      `/consumer-demands/${id}`,
      competitionId != null ? { params: { competitionId } } : undefined,
    ),
};

/** 消息图片元信息（与后端 MessageImageDto 对应）。 */
export interface MessageImage {
  /** 相对服务端根的路径，形如 /uploads/message-images/xxx.png */
  url: string;
  /** 落盘文件名（删除消息时由服务端清理）。 */
  filename: string;
}

export interface MessageItem {
  id: number;
  title: string;
  content: string;
  senderId: number;
  competitionId: number | null;
  targetsAll: boolean;
  targetUserIds: string;
  /** 消息附带图片（JSON 数组反序列化后的元信息列表）。 */
  images?: MessageImage[];
  createdAt: string;
  updatedAt: string;
  senderName?: string;
}

export interface InboxItem {
  recipientId: number;
  read: boolean;
  readAt: string | null;
  message: MessageItem;
  senderName: string;
}

export interface SentItem extends MessageItem {
  _count: { recipients: number };
  senderName: string;
}

/** 消息中心接口集合。收件箱 / 未读 / 已读以当前用户维度，绕过本地缓存实时拉取。 */
export const messagesApi = {
  /** 可选收件人（发布者同比赛 / 超管全部，超管可附加 competitionId 过滤）。 */
  selectableUsers: (competitionId?: number) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    return api.get("/messages/selectable-users", { params, cache: false });
  },
  /** 发布消息。targetsAll 与 targetUserIds 取并集去重。超管可附加 competitionId 把范围收敛到指定比赛。 */
  create: (data: {
    title: string;
    content: string;
    targetsAll?: boolean;
    targetUserIds?: number[];
    competitionId?: number;
    images?: MessageImage[];
  }) => api.post("/messages", data),
  /** 上传单张消息图片（multipart/form-data，字段名 "file"），返回 { url, filename }。 */
  uploadImage: (file: File): Promise<MessageImage> => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post("/messages/upload-image", fd);
  },
  /** 当前用户收件箱。 */
  inbox: (): Promise<InboxItem[]> => api.get("/messages/inbox", { cache: false }),
  /** 当前用户已发布消息。 */
  sent: (): Promise<SentItem[]> => api.get("/messages/sent", { cache: false }),
  /** 未读计数。 */
  unreadCount: (): Promise<{ count: number }> => api.get("/messages/unread-count", { cache: false }),
  /** 标记单条已读。 */
  markRead: (id: number) => api.patch(`/messages/${id}/read`),
  /** 全部标记为已读。 */
  markAllRead: () => api.post("/messages/read-all"),
  /** 删除已发布消息。 */
  remove: (id: number) => api.delete(`/messages/${id}`),
};

// ===================== 股票系统 =====================
export const stockApi = {
  // 股票列表 / 详情 / K线
  list: (page = 1, pageSize = 100, competitionId?: number) => {
    const params: Record<string, unknown> = { page, pageSize };
    if (competitionId != null) params.competitionId = competitionId;
    return api.get("/stocks", { params, cache: false });
  },
  get: (id: number) => api.get(`/stocks/${id}`),
  candles: (id: number) => api.get(`/stocks/${id}/candles`, { cache: false }),
  /** PB 联动下拉数据源：返回比赛内公司及其可绑定的数值型产业字段（cache:false 避免过期）。 */
  pbSources: (competitionId?: number) => {
    const params: Record<string, unknown> = {};
    if (competitionId != null) params.competitionId = competitionId;
    return api.get("/stocks/pb-sources", { params, cache: false });
  },
  create: (data: CreateStockInput) => api.post("/stocks", data),
  update: (id: number, data: UpdateStockInput) => api.patch(`/stocks/${id}`, data),
  remove: (id: number, competitionId?: number | null) =>
    api.delete(`/stocks/${id}`, competitionId != null ? { params: { competitionId } } : undefined),

  // 资金账户
  listAccounts: (competitionId: number) => {
    const params: Record<string, unknown> = { competitionId };
    return api.get("/stocks/accounts/list", { params, cache: false });
  },
  /** 账户总览（仅超级管理员）：可用资金 / 持仓 / 总资产 / 历史盈亏 */
  accountOverview: (competitionId: number) => {
    const params: Record<string, unknown> = { competitionId };
    return api.get("/stocks/accounts/overview", { params, cache: false });
  },
  getAccount: (id: number) => api.get(`/stocks/accounts/${id}`),
  accountHoldings: (id: number) => api.get(`/stocks/accounts/${id}/holdings`),
  createAccount: (data: CreateStockFundsAccountInput) => api.post("/stocks/accounts", data),
  updateAccount: (id: number, data: UpdateStockFundsAccountInput) => api.patch(`/stocks/accounts/${id}`, data),
  removeAccount: (id: number) => api.delete(`/stocks/accounts/${id}`),

  // 订单
  listOrders: (competitionId: number, stockId?: number, fundsAccountId?: number) => {
    const params: Record<string, unknown> = { competitionId };
    if (stockId != null) params.stockId = stockId;
    if (fundsAccountId != null) params.fundsAccountId = fundsAccountId;
    return api.get("/stocks/orders/list", { params });
  },
  placeOrder: (data: CreateStockOrderInput) => api.post("/stocks/orders", data),
  cancelOrder: (id: number) => api.delete(`/stocks/orders/${id}`),

  // 持仓
  listHoldings: (competitionId: number, accountId?: number) => {
    const params: Record<string, unknown> = { competitionId };
    if (accountId != null) params.accountId = accountId;
    return api.get("/stocks/holdings/list", { params, cache: false });
  },

  // 推进轮次（高级管理）
  advanceRound: (
    competitionId: number,
    dto: {
      stockIds?: number[];
      marketMaker?: { enabled?: boolean; spreadPct?: number; levels?: number; baseQuantity?: number };
      stockConfig?: {
        limitPct?: number;
        maxMovePct?: number;
        happinessImpact?: number;
        carbonImpact?: number;
        mmDepthPct?: number;
        mmSpreadPct?: number;
        interventionMode?: "regression" | "expand-limit";
        regressionPct?: number;
        tradePriceWeight?: number;
        carbonSaturateRatio?: number;
      };
    } = {},
  ) => api.post(`/stocks/advance-round?competitionId=${competitionId}`, dto),
};
