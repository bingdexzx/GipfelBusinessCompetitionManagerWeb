#!/usr/bin/env bash
# 隔离单测：验证 scripts/deploy-linux.sh 的 normalize_ip 与「无域名部署时公网 IP / 端口」契约。
# 不依赖真实 root / 网络 / 服务器，仅验证分支与源码契约。
#
# 运行（可从任意 cwd 运行）：bash tests/deploy_public_ip_test.sh
# 退出码：0 = 全部通过；1 = 有用例失败；2 = 环境错误（找不到被测脚本，区别于"用例失败"）
#
# 审计 X-15 修复点：
#   ① 改前第 7 行用 `SCRIPT="$PWD/scripts/deploy-linux.sh"` 定位被测脚本 —— 只要 cwd 不是仓库根
#      （例如 `cd tests && bash deploy_public_ip_test.sh`，或被其它脚本以绝对路径调用），`sed`
#      就读不到文件、`source` 到空内容、`normalize_ip` 未定义，断言成片 FAIL 且以 1 退出，
#      看起来像"被测脚本回归"。
#      实测改前：在 tests/ 目录内运行 → `结果：PASS=8 FAIL=14`、exit 1，并伴随
#      `normalize_ip: command not found`；在仓库根运行 → `PASS=22 FAIL=0`、exit 0。
#      现在一律用 BASH_SOURCE 解析仓库根，找不到被测文件时以退出码 2 报"环境错误"。
#   ② 改前第 32-68 行复刻并断言了 deploy-linux.sh 中**已被删除**的交互式 read 分支
#      （TTY / READ_VAL / READ_INVALID / READ_TIMEOUT）。该脚本以 `exec 0</dev/null` 运行
#      （非 TTY），`read` 恒为 EOF，属死代码。现在删除这段镜像实现，改为断言当前真实契约。
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/deploy-linux.sh"
LIB="$REPO_ROOT/scripts/lib/deploy-common.sh"

if [[ ! -f "$SCRIPT" ]]; then
    echo "[环境错误] 找不到被测脚本：$SCRIPT" >&2
    echo "           请在仓库内运行（本文件位置：$SCRIPT_DIR）" >&2
    exit 2
fi
if [[ ! -f "$LIB" ]]; then
    echo "[环境错误] 找不到公共库：$LIB" >&2
    exit 2
fi

# 仅抽取被测脚本中的函数定义并 source（避免执行主流程的 root/网络操作）
# shellcheck disable=SC1090
source <(sed -n '/^normalize_ip()/,/^}/p' "$SCRIPT")
# shellcheck disable=SC1090
source <(sed -n '/^_probe_public_ip()/,/^}/p' "$SCRIPT")
# 端口解析直接用生产实现（X-08 已抽到 scripts/lib/deploy-common.sh），不再复刻
# shellcheck disable=SC1090
source "$LIB"

PASS=0; FAIL=0
# 审计 X-01：((PASS++)) 在 PASS=0 时求值为 0 → 返回状态 1，在 set -e 下会中止脚本。
# 本文件未开 set -e，但仍统一改成不依赖算术表达式退出状态的写法。
assert_eq() {
    local desc="$1" got="$2" exp="$3"
    if [[ "$got" == "$exp" ]]; then
        PASS=$((PASS+1)); echo "  PASS  $desc"
    else
        FAIL=$((FAIL+1)); echo "  FAIL  $desc  (got=[$got] exp=[$exp])"
    fi
}
# 源码级契约断言：pattern 必须（或必须不）出现在被测文件中
assert_src() {
    local desc="$1" pattern="$2" file="$3" want="${4:-yes}"
    local hit="no"
    grep -qE "$pattern" "$file" && hit="yes"
    assert_eq "$desc" "$hit" "$want"
}

echo "[1] normalize_ip 规范化（取自 $SCRIPT 的真实实现）"
assert_eq "纯 IPv4"            "$(normalize_ip '43.142.77.225')"            "43.142.77.225"
assert_eq "IPv4 带路径"        "$(normalize_ip 'http://43.142.77.225/')"   "43.142.77.225"
assert_eq "IPv4 带端口"        "$(normalize_ip '43.142.77.225:8120')"      "43.142.77.225"
assert_eq "IPv4 带 scheme+端口+路径" "$(normalize_ip 'https://43.142.77.225:8120/x')" "43.142.77.225"
assert_eq "IPv6 带方括号"      "$(normalize_ip '[2001:db8::1]')"           "[2001:db8::1]"
assert_eq "IPv6 方括号+端口"  "$(normalize_ip 'http://[2001:db8::1]:8120/')" "[2001:db8::1]"
assert_eq "裸 IPv6"            "$(normalize_ip '2001:db8::1')"             "2001:db8::1"
assert_eq "裸 IPv6 带路径"    "$(normalize_ip '2001:db8::1/path')"        "2001:db8::1"

echo "[2] 无域名部署：公网 IP 优先级与 .env 落盘契约（源码级）"
assert_src "脚本以 exec 0</dev/null 运行（非 TTY，交互 read 必为死代码）" \
    'exec 0</dev/null' "$SCRIPT" yes
assert_src "已不存在交互式 read 分支 READ_VAL"    'READ_VAL'    "$SCRIPT" no
assert_src "已不存在交互式 read 分支 READ_INVALID" 'READ_INVALID' "$SCRIPT" no
assert_src "已不存在交互式 read 分支 READ_TIMEOUT" 'READ_TIMEOUT' "$SCRIPT" no
assert_src "已有 --public-ip 显式分支" \
    'if \[\[ -n "\$PUBLIC_IP" \]\]; then' "$SCRIPT" yes
assert_src "已调用 _probe_public_ip 做自动探测" \
    '_probe_public_ip' "$SCRIPT" yes
assert_src "探测失败时不写 LOG_VIEWER_PUBLIC_URL" \
    '未写入 LOG_VIEWER_PUBLIC_URL' "$SCRIPT" yes
assert_src "写入 URL 时端口取自 LOG_VIEWER_PORT 解析结果" \
    'LOG_VIEWER_PUBLIC_URL=http://\$\{LV_PUBLIC_IP\}:\$\{LV_PORT\}/' "$SCRIPT" yes
assert_src "IPv6 写入时补方括号" \
    'LOG_VIEWER_PUBLIC_URL=http://\[\$\{LV_PUBLIC_IP\}\]:\$\{LV_PORT\}/' "$SCRIPT" yes

# 优先顺序：--public-ip 分支必须出现在 _probe_public_ip 调用之前
_line_public_ip="$(grep -nE '^[[:space:]]*if \[\[ -n "\$PUBLIC_IP" \]\]; then' "$SCRIPT" | head -1 | cut -d: -f1)"
_line_probe="$(grep -nE '\$\(_probe_public_ip\)' "$SCRIPT" | head -1 | cut -d: -f1)"
if [[ -n "$_line_public_ip" && -n "$_line_probe" && "$_line_public_ip" -lt "$_line_probe" ]]; then
    assert_eq "--public-ip 判定在自动探测之前（优先级）" "yes" "yes"
else
    assert_eq "--public-ip 判定在自动探测之前（优先级）" \
        "public_ip@${_line_public_ip:-?} probe@${_line_probe:-?}" "yes"
fi

echo "[3] 端口来源：.env 的 LOG_VIEWER_PORT（生产实现 log_viewer_port）"
TMPD="$(mktemp -d "${TMPDIR:-/tmp}/gipfel-x15.XXXXXX")" || { echo "[环境错误] mktemp 失败" >&2; exit 2; }
trap 'rm -rf "$TMPD"' EXIT
printf 'LOG_VIEWER_PORT=9000\n' > "$TMPD/env.9000"
printf 'LOG_VIEWER_PORT=abc\n'  > "$TMPD/env.bad"
printf 'LOG_VIEWER_PORT=99999\n' > "$TMPD/env.range"
printf 'DJANGO_ALLOWED_HOSTS=1.2.3.4\n' > "$TMPD/env.noport"
assert_eq "默认端口 8120（.env 无该键）" "$(log_viewer_port "$TMPD/env.noport")" "8120"
assert_eq "默认端口 8120（.env 不存在）" "$(log_viewer_port "$TMPD/nope.env")"  "8120"
assert_eq "读取 .env 的 9000"            "$(log_viewer_port "$TMPD/env.9000")"  "9000"
assert_eq "非数字回退 8120"              "$(log_viewer_port "$TMPD/env.bad")"   "8120"
assert_eq "越界回退 8120"                "$(log_viewer_port "$TMPD/env.range")" "8120"

echo "[4] 无域名部署 URL 拼装（真实 normalize_ip + 真实 log_viewer_port）"
# 复刻 deploy-linux.sh:296-308 的拼装：PORT 来自生产实现，IP 来自生产实现
compose() {
    local __raw_ip="$1" __env="$2" __ip __port
    __port="$(log_viewer_port "$__env")"
    __ip="$(normalize_ip "$__raw_ip")"
    [[ -z "$__ip" ]] && { printf 'SKIP_NO_PROBE'; return 0; }
    if [[ "$__ip" == *:* && "$__ip" != \[* ]]; then
        printf 'http://[%s]:%s/' "$__ip" "$__port"
    else
        printf 'http://%s:%s/' "$__ip" "$__port"
    fi
}
assert_eq "--public-ip IPv4"          "$(compose '43.142.77.225' "$TMPD/env.noport")" "http://43.142.77.225:8120/"
assert_eq "--public-ip 带 scheme"     "$(compose 'http://43.142.77.225/' "$TMPD/env.noport")" "http://43.142.77.225:8120/"
assert_eq "--public-ip IPv6 加括号"   "$(compose '2001:db8::1' "$TMPD/env.noport")" "http://[2001:db8::1]:8120/"
assert_eq "端口随 .env 变化（9000）"  "$(compose '1.2.3.4' "$TMPD/env.9000")" "http://1.2.3.4:9000/"
assert_eq "非法端口回退后拼装"        "$(compose '1.2.3.4' "$TMPD/env.bad")"  "http://1.2.3.4:8120/"
assert_eq "探测失败（空）→ 不写 URL"  "$(compose '' "$TMPD/env.noport")"      "SKIP_NO_PROBE"

echo "[5] 结尾提示 IP 显示（修复：不得覆盖 --public-ip，否则误报「未获取到 IP」）"
# 复刻脚本结尾摘要逻辑：PUBLIC_IP 已被 --public-ip 占用；此处仅在其为空时经 _probe_public_ip() 探测。
summary() {
    local PUBLIC_IP="$1"; local PUBLIC_IP_SET="$2"; local PROBE_VAL="$3"
    local PUBLIC_IP_HINT=""
    if [[ -z "$PUBLIC_IP" ]]; then
        # 复刻 _probe_public_ip 行为：探测成功返回 IP，失败返回空
        PUBLIC_IP="$PROBE_VAL"
    fi
    if [[ -z "$PUBLIC_IP" ]]; then
        PUBLIC_IP_HINT="HINT_FAIL"
        PUBLIC_IP="<公网IP>"
    elif [[ "$PUBLIC_IP_SET" == "1" ]]; then
        PUBLIC_IP_HINT="HINT_USER"
    else
        PUBLIC_IP_HINT=""
    fi
    echo "${PUBLIC_IP}|${PUBLIC_IP_HINT}"
}
assert_eq "--public-ip 时显示指定 IP（不误报）" "$(summary '43.142.77.225' 1 '')" "43.142.77.225|HINT_USER"
assert_eq "--public-ip+探测失败仍显示指定 IP"  "$(summary '43.142.77.225' 1 '')" "43.142.77.225|HINT_USER"
assert_eq "未指定+探测成功显示探测 IP"        "$(summary '' 0 '1.2.3.4')"        "1.2.3.4|"
assert_eq "未指定+探测失败显示 FAIL 提示"     "$(summary '' 0 '')"               "<公网IP>|HINT_FAIL"
assert_src "结尾只在 PUBLIC_IP 为空时才探测（不覆盖用户传入值）" \
    'if \[\[ -z "\$PUBLIC_IP" \]\]; then' "$SCRIPT" yes

echo "[6] _probe_public_ip 不卡死（curl 由 timeout 硬包裹）"
assert_eq "_probe_public_ip 已从被测脚本 source 为函数" "$(type -t _probe_public_ip)" "function"
assert_src "curl 由 timeout 硬包裹（防 DNS 解析卡死）" \
    'timeout 8 curl -s --max-time 6' "$SCRIPT" yes

echo
echo "结果：PASS=$PASS FAIL=$FAIL（仓库根：$REPO_ROOT）"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
