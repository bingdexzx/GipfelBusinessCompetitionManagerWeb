# 压力测试工具使用指南

## 架构：为什么是 `.bat` + `.ps1` 两个文件

每个工具都由两个文件组成：

| 文件 | 作用 | 编码要求 |
|------|------|----------|
| `xxx.bat` | 纯 ASCII 启动器，只负责调用 PowerShell | **ASCII + CRLF**（不得有中文、不得 LF） |
| `xxx.ps1` | 真正的测试逻辑（含全部中文提示） | **UTF-8 带 BOM + CRLF** |

这样拆分的原因（都是踩过的坑）：

1. **`.bat` 必须是 CRLF**。用 LF 行尾时 cmd.exe 会把语句从中间拆开，报出
   `'xxx' is not recognized`、`-eq was unexpected at this time` 之类
   与真实原因完全无关的错误，极难定位。
2. **中文不要写在 `.bat` 里**。历史上曾用 `echo` 从 `.bat` 拼出 PowerShell 脚本，
   cmd 在 `chcp 65001` 下写文件时会把多字节字符截断（`次` → `娆?`），
   被吞掉的字节还会连带破坏引号配对，生成出语法错误的脚本。
3. **`.ps1` 必须带 UTF-8 BOM**。Windows PowerShell 5.1 对无 BOM 的文件按
   ANSI/GBK 解码，中文会变乱码，甚至破坏字符串引号。

仓库根的 `.gitattributes` 已锁定这些规则（`*.bat` / `*.ps1` 强制 CRLF，`*.sh` 强制 LF）。

## 工具一览

| 工具 | 用途 |
|------|------|
| `stress-test.bat` | 完整压力测试：多端点、多并发档位、认证、报告落盘 |
| `quick-test.bat` | 快速高并发检查：性能评分 + 优化建议 |
| `simple-test.bat` / `test-simple.bat` | 连通性测试：端点可达性 + 顺序延迟采样 |
| `view-results.bat` | 查看历史报告与 CSV 明细分析 |

也都可以直接用 PowerShell 调用，并传参跳过交互：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stress-test.ps1 `
  -ServerUrl http://your-domain.com -Concurrent 50 -Total 500 -EndpointKey 1
```

## 测试端点

| 序号 | 端点 | 说明 | 方法 | 认证 |
|------|------|------|------|------|
| 1 | /api/health | 健康检查 | GET | 无需 |
| 2 | /api/version | 版本信息 | GET | 无需 |
| 3 | /api/auth/login | 用户登录 | POST | 无需 |
| 4 | /api/competitions | 比赛列表 | GET | 需要 |
| 5 | /api/companies | 公司列表 | GET | 需要 |
| 6 | /api/materials | 原料列表 | GET | 需要 |
| 7 | /api/regions | 区域列表 | GET | 需要 |
| 8 | /api/stocks | 股票数据 | GET | 需要 |
| 9 | /api/maps/full | 地图数据 | GET | 需要 |

### 认证

选择需要认证的端点（4–9）时，脚本会给出三个选项，**用第 1 种即可，不必自己找 Token**：

```
此端点需要认证，请选择获取方式:
  1. 用账号密码自动登录换取（最省事）
  2. 手动粘贴已有 Token
  3. 不带认证继续（预期会返回 401）
```

#### 方式 1：自动登录（推荐）

输入一个管理员账号密码，脚本自己调 `POST /api/auth/login` 取回 token。

> ⚠ 后端登录会「**顶号下线**」：`LoginView` 每次登录都会把 `token_version` 加一并踢掉旧连接，
> 所以用完这个方式后，**浏览器里的登录态会立即失效**，需要重新登录一次。
> 如果不想影响正在用的浏览器会话，请改用方式 2。

#### 方式 2：手动粘贴 Token（最省事，且不影响浏览器会话）

Token 存在浏览器的 localStorage 里，用 Console 一行命令就能拿到：

1. 浏览器登录系统，按 `F12` 打开开发者工具
2. 切到 **Console** 面板，粘贴执行：

```js
localStorage.getItem(Object.keys(localStorage).find(k => k.endsWith('__token')))
```

3. 输出的那串（**不含首尾引号**）就是 Token，粘贴进脚本即可

脚本对输入做了容错：即使你把整段 `Bearer xxx`、或带引号的 `"xxx"` 一起粘进去，也会自动清理。

如果 Console 方式不可用，再走 Network 面板：`F12 → Network → 点开任意 /api/ 请求 →
Request Headers → Authorization: Bearer xxx`，取 `xxx`。

### POST 登录

选择端点 3 时会提示输入用户名与密码，脚本用 `ConvertTo-Json` 生成请求体
（密码含引号/反斜杠也不会拼串出错）。

> 注意：登录失败累计 **10 次 / 5 分钟**会锁定 **15 分钟**（后端 `middleware.py`）。
> 脚本会把 429 明确提示出来，别反复试错密码。

## 测试档位

| 档位 | 并发 | 请求数 |
|------|------|--------|
| 快速 | 10 | 100 |
| 标准 | 50 | 500 |
| 压力 | 100 | 1000 |
| 高并发 | 200 | 2000 |

`stress-test.ps1` 另有「5 - 自定义」可手工输入并发与总请求数。

## 结果文件

报告写入 `scripts\test-results\`：

- `stress-test-YYYYMMDD-HHMMSS.txt` — 报告摘要
- `stress-test-YYYYMMDD-HHMMSS.csv` — 每条请求的耗时（升序），可用 Excel 画分布

用 `view-results.bat` 查看报告并自动做分桶统计。

## 实现说明

负载内核由 `_load-engine.ps1` 在运行时用 `Add-Type` 编译一小段 C# 实现：

- 用 `HttpClient` + `SemaphoreSlim` 控制并发，`Stopwatch` 逐请求计时
- 不用 PowerShell 脚本块做并发——PS 5.1 的脚本块在线程池上会争用同一个
  runspace 锁，并发上不去且计时失真
- 编译时必须显式加载并引用 `System.Net.Http`：PS 5.1 默认没加载该程序集，
  且 `Add-Type` 的默认引用集不含它（否则报
  「命名空间 System.Net 中不存在类型或命名空间名称 Http」）

## 性能评分参考

| 指标 | 优秀 | 良好 | 一般 | 需优化 |
|------|------|------|------|--------|
| RPS | ≥200 | ≥100 | ≥50 | <50 |
| 平均响应时间 | ≤100ms | ≤300ms | ≤1000ms | >1000ms |
| 成功率 | ≥99% | ≥95% | ≥90% | <90% |

## 常见问题

### 报 `'xxx' is not recognized as an internal or external command`

`.bat` 的行尾被改成了 LF。用支持 CRLF 的编辑器重新保存，或执行：

```powershell
$p = 'scripts\stress-test.bat'
$t = [IO.File]::ReadAllText($p).Replace("`r`n","`n").Replace("`n","`r`n")
[IO.File]::WriteAllText($p, $t, [Text.Encoding]::ASCII)
```

### 中文显示成乱码 / 提示「未对文件进行数字签名」

- 乱码：`.ps1` 丢了 UTF-8 BOM，请以 **UTF-8 带 BOM** 重新保存。
- 签名错误：用 `.bat` 启动（内部已带 `-ExecutionPolicy Bypass`），或执行
  `powershell -ExecutionPolicy Bypass -File ...`。

### 大量 401

需要认证的端点未提供有效 Bearer Token。

### 大量 400

测试登录端点时用户名/密码不正确。

### 全部「连接失败/超时」

1. 服务器地址错误或服务未启动
2. 防火墙未放行
3. 端点路径错误（注意不要带尾随斜杠）

### RPS 偏低

1. 增加 Daphne worker 数量
2. 核对 Nginx 缓冲/压缩配置
3. 检查数据库查询与索引
4. 考虑引入 Redis 缓存

## 更新日志

- v3.0：重构为 `.bat`（ASCII 启动器）+ `.ps1`（UTF-8 BOM 逻辑）双文件架构；
  修复 LF 行尾与中文编码导致脚本无法运行的问题；负载内核改用 C#；
  新增逐请求 CSV 明细与状态码分布；`.gitattributes` 锁定行尾规则
- v2.0：支持多 API 端点、Bearer Token、POST 请求
- v1.0：初始版本
