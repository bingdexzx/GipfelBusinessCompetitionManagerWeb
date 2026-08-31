// 服务器身份 realm：把「当前服务器地址」映射为确定性短指纹，用于把客户端本地数据
// （IndexedDB 全量副本库 + 账号级 localStorage）按「服务器」隔离，避免不同服务器
// （即便 admin 都是 id=1）的本地数据相互串档 / token 跨服务器冒用。
//
// 本模块是叶子模块（不依赖 config / accountStorage），缓存层与账号层都引用它，
// 以避免形成 import 环（accountStorage 已被 cache.ts 引用，不能反向引用 cache.ts）。

/** djb2a：稳定、无依赖、输出小写十六进制。 */
function hashRealm(s: string): string {
  let h = 5381 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h = (((h << 5) + h) ^ s.charCodeAt(i)) >>> 0;
  }
  return h.toString(16);
}

/** 由任意服务器地址（可空）计算 realm；空 / 非法返回固定哨兵，保证命名空间稳定。 */
export function realmForUrl(raw: string | null | undefined): string {
  if (!raw) return "noserver";
  let u = raw.trim();
  if (!/^https?:\/\//i.test(u)) u = "http://" + u;
  u = u.replace(/\/+$/, "").toLowerCase(); // 仅 protocol+host+port，不含路径
  return hashRealm(u);
}

let _realm: string | null = null;

/** 当前服务器的 realm（按当前 serverUrl 计算）。结果缓存，setServerUrl 时通过 resetServerRealm 失效。 */
export function getServerRealm(): string {
  if (_realm === null) {
    _realm = realmForUrl(localStorage.getItem("serverUrl"));
  }
  return _realm;
}

/** 失效 realm 缓存（服务器地址变更后调用）。 */
export function resetServerRealm(): void {
  _realm = null;
}

/**
 * 清理指定 realm 的全部本地数据：删除该 realm 下的 localStorage 账号键与 IndexedDB 全量副本库。
 * 切换服务器时使用，杜绝旧服务器数据与新服务器串档。fire-and-forget（不阻塞调用方）。
 */
export function clearRealmData(realm: string): void {
  try {
    const prefix = `acct_${realm}_`;
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) localStorage.removeItem(k);
    }
    if (typeof indexedDB !== "undefined" && (indexedDB as any).databases) {
      (indexedDB as any)
        .databases()
        .then((dbs: any[]) => {
          for (const d of dbs) {
            const n = d.name || "";
            if (n.startsWith(`gipfel-client-cache-${realm}-`)) {
              indexedDB.deleteDatabase(n);
            }
          }
        })
        .catch(() => {});
    }
  } catch {
    /* 忽略：清理失败不影响主流程 */
  }
}
