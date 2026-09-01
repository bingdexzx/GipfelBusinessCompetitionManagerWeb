#!/usr/bin/env bash
# 隔离单测：验证 deploy-linux.sh 中新增的 normalize_ip 与「公网 IP 解析优先级」逻辑。
# 不依赖真实 root / 网络 / 服务器，仅验证分支正确性。
# 运行：bash tests/deploy_public_ip_test.sh
set -uo pipefail

SCRIPT="$PWD/scripts/deploy-linux.sh"
# 仅抽取脚本中的 normalize_ip 函数定义并 source（避免执行主流程的 root/网络操作）
# shellcheck disable=SC1090
source <(sed -n '/^normalize_ip()/,/^}/p' "$SCRIPT")

PASS=0; FAIL=0
assert_eq() {
    local desc="$1" got="$2" exp="$3"
    if [[ "$got" == "$exp" ]]; then
        PASS=$((PASS+1)); echo "  PASS  $desc"
    else
        FAIL=$((FAIL+1)); echo "  FAIL  $desc  (got=[$got] exp=[$exp])"
    fi
}

echo "[1] normalize_ip 规范化"
assert_eq "纯 IPv4"            "$(normalize_ip '43.142.77.225')"            "43.142.77.225"
assert_eq "IPv4 带路径"        "$(normalize_ip 'http://43.142.77.225/')"   "43.142.77.225"
assert_eq "IPv4 带端口"        "$(normalize_ip '43.142.77.225:8120')"      "43.142.77.225"
assert_eq "IPv4 带 scheme+端口+路径" "$(normalize_ip 'https://43.142.77.225:8120/x')" "43.142.77.225"
assert_eq "IPv6 带方括号"      "$(normalize_ip '[2001:db8::1]')"           "[2001:db8::1]"
assert_eq "IPv6 方括号+端口"  "$(normalize_ip 'http://[2001:db8::1]:8120/')" "[2001:db8::1]"
assert_eq "裸 IPv6"            "$(normalize_ip '2001:db8::1')"             "2001:db8::1"
assert_eq "裸 IPv6 带路径"    "$(normalize_ip '2001:db8::1/path')"        "2001:db8::1"

echo "[2] 公网 IP 解析优先级（镜像脚本分支顺序：--public-ip > curl > read > 跳过）"
# 复刻脚本中的解析决策，返回最终写入 .env 的 URL 值（空表示跳过/由后端推导）
resolve() {
    local PUBLIC_IP="$1"; local DOMAIN="$2"; local TTY="$3"; local CURL_VAL="$4"; local READ_VAL="$5"
    local LV_PUBLIC_IP="" URL=""
    if [[ -n "$DOMAIN" ]]; then
        echo "DOMAIN_MODE"; return 0   # 有域名走 CORS 分支，不写 LOG_VIEWER_PUBLIC_URL
    fi
    if [[ -n "$PUBLIC_IP" ]]; then
        LV_PUBLIC_IP="$(normalize_ip "$PUBLIC_IP")"
    else
        LV_PUBLIC_IP="$CURL_VAL"
    fi
    if [[ -n "$LV_PUBLIC_IP" ]]; then
        LV_PUBLIC_IP="$(normalize_ip "$LV_PUBLIC_IP")"
        if [[ "$LV_PUBLIC_IP" == *:* && "$LV_PUBLIC_IP" != \[* ]]; then
            URL="http://[${LV_PUBLIC_IP}]:8120/"
        else
            URL="http://${LV_PUBLIC_IP}:8120/"
        fi
        echo "$URL"; return 0
    fi
    if [[ "$TTY" == "1" ]]; then
        if [[ -n "$READ_VAL" ]]; then
            local m; m="$(normalize_ip "$READ_VAL")"
            if [[ "$m" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || [[ "$m" == \[* ]] || [[ "$m" == *:* ]]; then
                if [[ "$m" == \[* ]]; then URL="http://${m}:8120/"
                elif [[ "$m" == *:* ]]; then URL="http://[${m}]:8120/"
                else URL="http://${m}:8120/"; fi
                echo "$URL"; return 0
            fi
            echo "READ_INVALID"; return 0
        fi
        echo "READ_TIMEOUT"; return 0
    fi
    echo "SKIP_NO_TTY"; return 0
}

assert_eq "显式 --public-ip 优先" "$(resolve '43.142.77.225' '' 0 '' '')" "http://43.142.77.225:8120/"
assert_eq "--public-ip 带 scheme 仍正确" "$(resolve 'http://43.142.77.225/' '' 0 '' '')" "http://43.142.77.225:8120/"
assert_eq "--public-ip IPv6 加括号" "$(resolve '2001:db8::1' '' 0 '' '')" "http://[2001:db8::1]:8120/"
assert_eq "curl 兜底成功"        "$(resolve '' '' 0 '1.2.3.4' '')"        "http://1.2.3.4:8120/"
assert_eq "curl 失败+TTY 手动填" "$(resolve '' '' 1 '' '9.9.9.9')"        "http://9.9.9.9:8120/"
assert_eq "curl 失败+TTY 输入非法" "$(resolve '' '' 1 '' 'notanip')"      "READ_INVALID"
assert_eq "curl 失败+TTY 超时"   "$(resolve '' '' 1 '' '')"               "READ_TIMEOUT"
assert_eq "curl 失败+非 TTY 跳过" "$(resolve '' '' 0 '' '')"              "SKIP_NO_TTY"
assert_eq "有域名走 CORS 不写"   "$(resolve '' 'comp.example.com' 0 '' '')" "DOMAIN_MODE"

echo
echo "结果：PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
