/**
 * 权限目录（前端镜像，与后端 backend/apps/common/permissions.py 同构）。
 * 修改时需与后端同步。
 */

export interface PermissionAction {
  key: string;
  action: string;
  label: string;
}

export interface PermissionDomain {
  key: string;
  label: string;
  group: string;
  actions: PermissionAction[];
  actionRank?: Record<string, number>;
}

export const DEFAULT_ACTION_RANKS: Record<string, number> = {
  view: 10,
  edit: 20,
  manage: 30,
  execute: 40,
  audit: 50,
};

const CONTRACT_ACTION_RANKS: Record<string, number> = {
  view: 10,
  audit: 20,
  execute: 30,
  manage: 40,
};

export const PERMISSION_CATALOG: PermissionDomain[] = [
  { key: "competition", label: "比赛管理", group: "比赛", actions: [{ key: "competition:manage", action: "manage", label: "管理（增删改）" }] },
  { key: "data:material", label: "原料管理", group: "数据", actions: [ { key: "data:material:view", action: "view", label: "查看" }, { key: "data:material:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:part", label: "零件管理", group: "数据", actions: [ { key: "data:part:view", action: "view", label: "查看" }, { key: "data:part:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:product", label: "产品管理", group: "数据", actions: [ { key: "data:product:view", action: "view", label: "查看" }, { key: "data:product:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:map", label: "地图管理", group: "数据", actions: [ { key: "data:map:view", action: "view", label: "查看" }, { key: "data:map:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:infrastructure", label: "基建管理", group: "数据", actions: [ { key: "data:infrastructure:view", action: "view", label: "查看" }, { key: "data:infrastructure:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:tech", label: "科技树管理", group: "数据", actions: [ { key: "data:tech:view", action: "view", label: "查看" }, { key: "data:tech:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:fuel", label: "燃料管理", group: "数据", actions: [ { key: "data:fuel:view", action: "view", label: "查看" }, { key: "data:fuel:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:vehicle", label: "载具管理", group: "数据", actions: [ { key: "data:vehicle:view", action: "view", label: "查看" }, { key: "data:vehicle:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:warehouse", label: "仓库管理", group: "数据", actions: [ { key: "data:warehouse:view", action: "view", label: "查看" }, { key: "data:warehouse:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:productionLine", label: "生产线管理", group: "数据", actions: [ { key: "data:productionLine:view", action: "view", label: "查看" }, { key: "data:productionLine:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "data:region", label: "区域管理", group: "区域", actions: [ { key: "data:region:view", action: "view", label: "查看" }, { key: "data:region:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "consumer-demand", label: "消费者需求", group: "区域", actions: [ { key: "consumer-demand:view", action: "view", label: "查看" }, { key: "consumer-demand:edit", action: "edit", label: "编辑（增删改）" } ] },
  { key: "contractType", label: "合同类型管理", group: "合同", actions: [ { key: "contractType:view", action: "view", label: "查看" }, { key: "contractType:manage", action: "manage", label: "管理（增删改）" } ] },
  { key: "contract", label: "合同管理", group: "合同", actionRank: CONTRACT_ACTION_RANKS, actions: [ { key: "contract:view", action: "view", label: "查看" }, { key: "contract:audit", action: "audit", label: "审核（公司范围）" }, { key: "contract:execute", action: "execute", label: "执行（比赛级）" }, { key: "contract:manage", action: "manage", label: "管理（新建/删除）" } ] },
  { key: "industryType", label: "产业类型管理", group: "产业", actions: [ { key: "industryType:view", action: "view", label: "查看" }, { key: "industryType:manage", action: "manage", label: "管理（增删改）" } ] },
  { key: "company", label: "公司管理", group: "产业", actions: [ { key: "company:view", action: "view", label: "查看（读取公司产业字段）" }, { key: "company:manage", action: "manage", label: "管理（增删改公司）" } ] },
  { key: "account", label: "账户管理", group: "系统", actions: [{ key: "account:manage", action: "manage", label: "管理（增删改账号与权限）" }] },
  { key: "message", label: "消息中心", group: "消息", actions: [ { key: "message:view", action: "view", label: "查看（收件箱/已发布/接收弹窗）" }, { key: "message:manage", action: "manage", label: "管理（发布/删除消息）" } ] },
  { key: "stock", label: "股票系统", group: "股票", actions: [ { key: "stock:view", action: "view", label: "查看行情" }, { key: "stock:edit", action: "edit", label: "低级管理" }, { key: "stock:manage", action: "manage", label: "高级管理" } ] },
];

export const ALL_PERMISSION_KEYS = PERMISSION_CATALOG.flatMap((d) => d.actions.map((a) => a.key));

export const PERMISSION_LABELS: Record<string, string> = PERMISSION_CATALOG.reduce(
  (acc, d) => { for (const a of d.actions) acc[a.key] = `${d.label} · ${a.label}`; return acc; },
  {} as Record<string, string>,
);

export const PERMISSION_GROUPS: { group: string; domains: PermissionDomain[] }[] = (() => {
  const map = new Map<string, PermissionDomain[]>();
  for (const d of PERMISSION_CATALOG) {
    if (!map.has(d.group)) map.set(d.group, []);
    map.get(d.group)!.push(d);
  }
  return Array.from(map.entries()).map(([group, domains]) => ({ group, domains }));
})();

export const DEPRECATED_PERMISSION_KEYS = ["settings:view", "settings:manage", "dashboard:view"];

function domainOf(key: string): string { const p = key.split(":"); return p.slice(0, -1).join(":"); }
function actionOf(key: string): string { return key.split(":").slice(-1)[0]; }
function domainActionRank(domain: string): Record<string, number> {
  const d = PERMISSION_CATALOG.find((x) => x.key === domain);
  return d?.actionRank ?? DEFAULT_ACTION_RANKS;
}

export function hasPermission(
  role: string | undefined,
  permissions: string[] | null | undefined,
  required: string | string[],
): boolean {
  if (role === "SUPER_ADMIN") return true;
  const req = Array.isArray(required) ? required : [required];
  if (req.length === 0) return true;
  const perms = permissions || [];
  for (const reqKey of req) {
    const domain = domainOf(reqKey);
    const reqAction = actionOf(reqKey);
    const reqRank = domainActionRank(domain)[reqAction] ?? 0;
    const satisfied = perms.some((p) => {
      if (domainOf(p) !== domain) return false;
      const userRank = domainActionRank(domain)[actionOf(p)] ?? 0;
      return userRank >= reqRank;
    });
    if (!satisfied) return false;
  }
  return true;
}
