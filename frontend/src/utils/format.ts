/**
 * 前端通用格式化工具（唯一真源）。
 * 消除多个视图中重复的匿名格式化函数（金额千分位、ISO 时间截断等）。
 *
 * 大数支持（千万京 10^23 级）：
 * - formatMoney 接受 string | number。大数以字符串形态经 API 出站（后端
 *   BigSafeJSONRenderer 把 >2^53 的 int 转字符串），此处用 BigInt 分组，
 *   绝不经 Number 化——JS double 在 2^53 以上会静默丢精度。
 * - formatMoneyCN 提供万/亿/兆/京/垓 中文单位紧凑显示（长金额看板场景）。
 */

/** 千万京（10^23）级安全判断：是否可安全当作 Number 处理（|n| ≤ 2^53）。 */
const JS_MAX_SAFE = 9007199254740991n; // BigInt(2^53 - 1)

function toBigIntSafe(s: string): bigint | null {
  try {
    const cleaned = s.trim().replace(/,/g, "");
    if (!/^[+-]?\d+(\.\d+)?$/.test(cleaned)) return null;
    // 小数部分截断进 BigInt（千分位只关心整数部分；小数由 frac 通道处理）
    const [intPart] = cleaned.split(".");
    return BigInt(intPart || "0");
  } catch {
    return null;
  }
}

/** 大数安全千分位：整数部分用 BigInt 分组，小数部分原样保留（最多 prec 位）。 */
function groupThousands(s: string, prec: number): string {
  const trimmed = s.trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
  const neg = trimmed.startsWith("-");
  const body = neg || trimmed.startsWith("+") ? trimmed.slice(1) : trimmed;
  const [intRaw, fracRaw = ""] = body.split(".");
  const intPart = intRaw || "0";
  // BigInt 分组（避免 Number 化大数）
  const bi = toBigIntSafe(intPart) ?? 0n;
  const grouped = bi.toLocaleString("en-US");
  const frac = prec > 0 && fracRaw ? "." + fracRaw.slice(0, prec) : "";
  return (neg ? "-" : "") + grouped + frac;
}

/**
 * 金额格式化：中文千分位、最多 2 位小数；null/NaN 显示"—"（与两处股票视图原 fmt 一致）。
 * 大数安全：超过 2^53 的字符串大数走 BigInt 分组（不经 Number，10^23+ 无损，
 * 小数截断到 2 位）；安全范围内的数值保持原有 Number.toLocaleString 行为（含四舍五入）。
 */
export function formatMoney(n: number | string | null | undefined): string {
  if (n == null || n === "") return "—";
  const s = String(n).trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(s)) return "—"; // NaN / 非数字串
  const bi = toBigIntSafe(s);
  const withinSafe =
    bi !== null && bi <= JS_MAX_SAFE && bi >= -JS_MAX_SAFE && !s.includes(".");
  if (withinSafe) {
    return Number(s).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  // 大数（或大数带小数）：整数部分 BigInt 分组 + 小数最多 2 位（截断，不四舍五入）
  return groupThousands(s, 2);
}

/** 中文数量级单位表：万 1e4 → 垓 1e20（覆盖千万京 10^23 以上两个数量级）。 */
const CN_UNITS: Array<{ label: string; exp: number }> = [
  { label: "垓", exp: 20 },
  { label: "京", exp: 16 },
  { label: "兆", exp: 12 },
  { label: "亿", exp: 8 },
  { label: "万", exp: 4 },
];

/**
 * 金额紧凑中文单位显示（大数安全）：如 1.23 京、456.7 万。
 * 选择能整除的最大单位；小于万原样千分位；负数保留符号。
 * @param keepSign 是否在正数前保留 +（默认否）
 */
export function formatMoneyCN(
  n: number | string | null | undefined,
  keepSign = false,
): string {
  if (n == null || n === "") return "—";
  const s = String(n).trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(s)) return "—";
  const neg = s.startsWith("-");
  const body = neg || s.startsWith("+") ? s.slice(1) : s;
  const bi = toBigIntSafe(body);
  if (bi === null) return "—";
  const abs = bi < 0n ? -bi : bi;

  for (const { label, exp } of CN_UNITS) {
    const divisor = 10n ** BigInt(exp);
    if (abs >= divisor) {
      // 整数部分 + 两位小数（截断），如 12345678901234567890 → 1.23 京
      const whole = abs / divisor;
      const frac = ((abs % divisor) * 100n) / divisor; // 两位小数（截断）
      const fracStr = frac === 0n ? "" : `.${frac.toString().padStart(2, "0").replace(/0$/, "")}`;
      const sign = neg ? "-" : keepSign ? "+" : "";
      return `${sign}${whole.toLocaleString("en-US")}${fracStr} ${label}`;
    }
  }
  // 小于万：千分位原样
  return (neg ? "-" : "") + groupThousands(body, 2);
}

/**
 * ISO 时间去秒截断（与全局 $formatTime 完全一致）。
 * 空值或非法日期返回 "-"；否则按 UTC 截断到秒（YYYY-MM-DD HH:mm:ss）。
 */
export function formatTime(val: string | Date | null | undefined): string {
  if (!val) return "-";
  const d = typeof val === "string" ? new Date(val) : val;
  if (isNaN(d.getTime())) return "-";
  return d.toISOString().replace("T", " ").substring(0, 19);
}
