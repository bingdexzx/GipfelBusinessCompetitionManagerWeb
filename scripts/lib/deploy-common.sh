#!/usr/bin/env bash
# ============================================================
# 部署脚本公共函数（被 deploy-linux.sh 与 update-from-github.sh 共同 source）
#
# 审计 X-08：日志查看器公网端口（LOG_VIEWER_PORT）原先在 deploy-linux.sh 里正确解析、
# 而在 update-from-github.sh 里被**硬编码成 8120**（`LOG_VIEWER_PUBLIC_URL` 与 `ufw allow`）。
# 于是把 .env 改成别的端口后，升级路径会把 URL/防火墙规则改回 8120，而 nginx 仍监听新端口：
# 前端按钮跳向错误端口、运维按提示查防火墙也会被误导。这里把解析逻辑抽成**唯一实现**，
# 两个脚本共用，避免再次漂移。
#
# 用法（在脚本里）：
#   _common="$(dirname "$0")/lib/deploy-common.sh"   # 或脚本自带路径
#   # shellcheck source=scripts/lib/deploy-common.sh
#   [[ -f "$_common" ]] && source "$_common"
# ============================================================

# 日志前缀（调用方可以覆盖 log/warn/err；这里只提供兜底，避免 source 顺序问题）
command -v log  >/dev/null 2>&1 || log()  { echo "[deploy] $*"; }
command -v warn >/dev/null 2>&1 || warn() { echo "[deploy][warn] $*" >&2; }
command -v err  >/dev/null 2>&1 || err()  { echo "[deploy][error] $*" >&2; exit 1; }

# 解析日志查看器 nginx 公网监听端口：取 .env 的 LOG_VIEWER_PORT（默认 8120），
# 缺失/非数字/越界（1-65535）一律兜底 8120 并告警。
# 该端口是 nginx 监听 0.0.0.0:<port>，与 daphne 内部 127.0.0.1:8121 是两个端口
# （前者 .env 控制、后者 service 模板硬编码），故意不等，避免同机抢端口。
log_viewer_port() {
    local _env="${1:-}"
    local _p="8120"
    if [[ -n "$_env" && -f "$_env" ]] && grep -qE '^[[:space:]]*LOG_VIEWER_PORT=' "$_env"; then
        _p=$(grep -E '^[[:space:]]*LOG_VIEWER_PORT=' "$_env" | head -1 | cut -d= -f2- \
            | tr -d '[:space:]' | sed -E "s/^['\"]//; s/['\"]$//")
        if ! [[ "$_p" =~ ^[0-9]+$ ]] || (( _p < 1 || _p > 65535 )); then
            warn "LOG_VIEWER_PORT=$_p 非法（需 1-65535 整数），回退默认 8120"
            _p="8120"
        fi
    fi
    printf '%s' "$_p"
}

# 兼容旧调用名（deploy-linux.sh 历史函数名）
_log_viewer_port() { log_viewer_port "${1:-}"; }

# 确保 `.env` 中某个 KEY 只有一条记录且值恰好为 want（审计 X-11）。
#
# 改前两个部署脚本用 `sed -i "s|^KEY=.*|&,${AH_ENTRY}|"` 追加：`&` 代表**整个匹配文本**，
# 探测到的公网 IP 变化时会反复追加（历史 IP 永久留在 DJANGO_ALLOWED_HOSTS 白名单里），
# 且同一 KEY 出现多行时 `sed` 会同时改写多行，而 `os.environ` 只认**第一条** —— 脚本输出与
# 实际生效值不一致，排查极具误导性。
# 现在的做法：先删掉全部同名行，再追加唯一一行；改完立刻回读断言只剩一条。
# 用法：set_env_single <env文件> <KEY> <值>
set_env_single() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    [[ -n "$env_file" && -n "$key" ]] || return 1
    touch "$env_file"
    local tmp="${env_file}.tmp.$$"
    if ! grep -vE "^[[:space:]]*${key}=" "$env_file" > "$tmp" 2>/dev/null; then
        : > "$tmp"
    fi
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    mv -f "$tmp" "$env_file"
    # 回读断言：该 KEY 只能有一条
    local n
    n=$(grep -cE "^[[:space:]]*${key}=" "$env_file" 2>/dev/null || true)
    if [[ "${n:-0}" != "1" ]]; then
        warn "写入 ${key} 后回读发现 ${n:-0} 条记录（期望 1 条），请检查 ${env_file}"
        return 1
    fi
    return 0
}

# 把 entry 追加进逗号分隔的 KEY 值（去重），并保证该 KEY 只有一条记录（审计 X-11）。
# 用法：append_env_entry <env文件> <KEY> <entry> [默认值]
append_env_entry() {
    local env_file="$1"
    local key="$2"
    local entry="$3"
    local default_value="${4:-}"
    [[ -n "$entry" ]] || return 1
    local cur=""
    if [[ -f "$env_file" ]]; then
        cur=$(grep -E "^[[:space:]]*${key}=" "$env_file" | head -1 | cut -d= -f2- || true)
    fi
    [[ -n "$cur" ]] || cur="$default_value"
    # 逗号分隔去重（保留原有顺序）
    local out="" item
    local IFS=','
    for item in $cur; do
        item="${item//[[:space:]]/}"
        [[ -z "$item" ]] && continue
        [[ ",$out," == *",$item,"* ]] && continue
        out="${out:+$out,}$item"
    done
    if [[ ",$out," != *",$entry,"* ]]; then
        out="${out:+$out,}$entry"
    fi
    set_env_single "$env_file" "$key" "$out"
    printf '%s' "$out"
}

# 确保 .env 里的 LOG_VIEWER_PUBLIC_URL 与给定端口一致（审计 X-08）。
# 用法：ensure_log_viewer_public_url <env文件> <公网IP> <端口>
ensure_log_viewer_public_url() {
    local env_file="$1"
    local ip="$2"
    local port="$3"
    [[ -n "$env_file" && -n "$ip" && -n "$port" ]] || return 1
    # IPv6 需要方括号
    local host="$ip"
    if [[ "$ip" == *:* && "$ip" != \[* ]]; then
        host="[$ip]"
    fi
    local want="http://${host}:${port}/"
    # 审计 X-11：用「删全部同名行 + 追加唯一一行」替代 sed 整行替换（避免多行同时被改）
    set_env_single "$env_file" "LOG_VIEWER_PUBLIC_URL" "$want"
    printf '%s' "LOG_VIEWER_PUBLIC_URL=${want}"
}

# 自检：.env 的 LOG_VIEWER_PUBLIC_URL 端口 与 nginx vhost 的 listen 端口必须一致（审计 X-08）。
# 用法：assert_log_viewer_port_consistent <env文件> <vhost文件>
# 返回 0 一致 / 1 不一致（不一致时打印诊断）
assert_log_viewer_port_consistent() {
    local env_file="$1"
    local vhost="$2"
    [[ -f "$env_file" && -f "$vhost" ]] || return 0
    local url_port listen_port
    url_port=$(grep -E '^LOG_VIEWER_PUBLIC_URL=' "$env_file" | head -1 \
        | sed -E 's|.*:([0-9]+)/?.*|\1|')
    # vhost 里监听该端口的 server 块（取第一个 listen 的端口号集合即可）
    listen_port=$(grep -E '^[[:space:]]*listen[[:space:]]+[0-9]+' "$vhost" | head -1 \
        | sed -E 's|^[[:space:]]*listen[[:space:]]+([0-9]+).*|\1|')
    if [[ -n "$url_port" && -n "$listen_port" && "$url_port" != "$listen_port" ]]; then
        warn "端口不一致：.env 的 LOG_VIEWER_PUBLIC_URL 用 ${url_port}，nginx listen 用 ${listen_port}"
        return 1
    fi
    return 0
}
