import { pinyin } from "pinyin-pro";

/**
 * 名称 → 拼音标识（小写全拼、去声调、剔除非字母数字下划线）。
 * 如「矿点数量」→ kuangdianshuliang；多音字由 pinyin-pro 处理。
 * 非汉字（数字/英文）原样保留；非字母数字下划线字符被剔除。
 */
export function toPinyinKey(name: string): string {
  const arr = pinyin(name, { toneType: "none", type: "array" });
  return arr
    .join("")
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, "");
}
