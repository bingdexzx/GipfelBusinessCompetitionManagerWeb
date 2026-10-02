# ============================================================
#  Gipfel 压测共享引擎
#  供 stress-test.ps1 / quick-test.ps1 / simple-test.ps1 复用。
#
#  为什么用 C# 内核而不是纯 PowerShell 并发：
#    PowerShell 5.1 的脚本块在线程池上执行会争用同一个 runspace 锁，
#    并发上不去且计时不准。C# 版用 HttpClient + SemaphoreSlim，
#    计时精确、无 runspace 争用、也不存在闭包变量捕获问题。
# ============================================================

# ---------------- 端点目录 ----------------
$script:GipfelEndpoints = @(
    @{ Key = '1'; Path = '/api/health';       Name = '健康检查'; Auth = $false; Method = 'GET'  },
    @{ Key = '2'; Path = '/api/version';      Name = '版本信息'; Auth = $false; Method = 'GET'  },
    @{ Key = '3'; Path = '/api/auth/login';   Name = '用户登录'; Auth = $false; Method = 'POST' },
    @{ Key = '4'; Path = '/api/competitions'; Name = '比赛列表'; Auth = $true;  Method = 'GET'  },
    @{ Key = '5'; Path = '/api/companies';    Name = '公司列表'; Auth = $true;  Method = 'GET'  },
    @{ Key = '6'; Path = '/api/materials';    Name = '原料列表'; Auth = $true;  Method = 'GET'  },
    @{ Key = '7'; Path = '/api/regions';      Name = '区域列表'; Auth = $true;  Method = 'GET'  },
    @{ Key = '8'; Path = '/api/stocks';       Name = '股票数据'; Auth = $true;  Method = 'GET'  },
    @{ Key = '9'; Path = '/api/maps/full';    Name = '地图数据'; Auth = $true;  Method = 'GET'  }
)

function Write-GipfelBanner {
    param([string]$Title)
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ("  " + $Title) -ForegroundColor Cyan
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
}

function Read-GipfelServerUrl {
    Write-Host '请输入服务器地址' -ForegroundColor Yellow
    Write-Host '示例: http://123.456.789.0 或 http://your-domain.com' -ForegroundColor DarkGray
    $u = (Read-Host '服务器地址').Trim()
    if ([string]::IsNullOrWhiteSpace($u)) {
        throw '服务器地址不能为空！'
    }
    if (-not $u.StartsWith('http://') -and -not $u.StartsWith('https://')) {
        $u = 'http://' + $u
    }
    return $u.TrimEnd('/')
}

function Show-GipfelEndpoints {
    Write-Host '请选择测试端点:' -ForegroundColor Yellow
    Write-Host ''
    foreach ($e in $script:GipfelEndpoints) {
        $auth = if ($e.Auth) { '需认证' } else { '无需认证' }
        Write-Host ("  {0}. {1,-20} {2} ({3}, {4})" -f $e.Key, $e.Path, $e.Name, $e.Method, $auth)
    }
    Write-Host ''
}

function Read-GipfelEndpoint {
    Show-GipfelEndpoints
    $k = (Read-Host '请输入数字 (1-9)').Trim()
    $hit = $script:GipfelEndpoints | Where-Object { $_.Key -eq $k } | Select-Object -First 1
    if (-not $hit) {
        Write-Host '无效选择，使用默认: /api/health (健康检查)' -ForegroundColor Yellow
        $hit = $script:GipfelEndpoints[0]
    }
    return $hit
}

function Read-GipfelSecret {
    param([string]$Prompt = '密码')
    $sec = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try   { return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

# ---------------- 用账号密码换取 token ----------------
# 后端契约（apps/auth/views.py LoginView + common/response.py 统一包装）：
#   POST /api/auth/login  {username,password}
# ---------------- 从异常里提取 HTTP 状态码与后端中文 message ----------------
# 兼容两种宿主：PS 5.1 的 HttpWebResponse.GetResponseStream() 与
# PS 7 的 HttpResponseMessage.Content。取不到就退回异常自身的消息。
function Get-GipfelErrorInfo {
    param([Parameter(Mandatory)]$ErrorRecord)

    $code = 0
    $msg  = ''
    try { $msg = [string]$ErrorRecord.Exception.Message } catch { }

    try {
        $resp = $ErrorRecord.Exception.Response
        if ($resp) {
            try { $code = [int]$resp.StatusCode } catch { }
            $raw = $null
            try {
                if (@($resp.PSObject.Methods.Name) -contains 'GetResponseStream') {
                    $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
                    $raw = $sr.ReadToEnd(); $sr.Close()
                } elseif ($resp.Content) {
                    $raw = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                }
            } catch { }
            if ($raw) {
                # 后端统一包装里的中文 message 比 HTTP 状态码更有信息量
                try {
                    $o = $raw | ConvertFrom-Json
                    if ($o.message) { $msg = [string]$o.message }
                } catch { }
            }
        }
    } catch { }

    return @{ StatusCode = $code; Message = $msg }
}

#   → {"code":0,"message":"成功","data":{"token":"...","user":{...}}}
# ⚠ 后端登录会「顶号下线」（token_version +1 并踢掉旧连接），
#   因此用本函数登录后，浏览器里的登录态会立即失效，需要重新登录。
function Get-GipfelToken {
    param(
        [Parameter(Mandatory)][string]$ServerUrl,
        [Parameter(Mandatory)][string]$User,
        [Parameter(Mandatory)][string]$Pass
    )

    $body = @{ username = $User; password = $Pass } | ConvertTo-Json -Compress
    $uri  = $ServerUrl.TrimEnd('/') + '/api/auth/login'

    try {
        $resp = Invoke-RestMethod -Uri $uri -Method Post -Body $body `
                                  -ContentType 'application/json; charset=utf-8' -TimeoutSec 20
    }
    catch {
        $info = Get-GipfelErrorInfo -ErrorRecord $_
        switch ($info.StatusCode) {
            401 { throw ('登录失败：用户名或密码错误（后端返回 401）') }
            403 { throw ('登录失败：该账号已被禁用（后端返回 403）') }
            429 { throw ('登录失败：已触发登录失败锁定（10 次/5 分钟 → 锁 15 分钟），请等待后重试') }
            default { throw ('登录请求失败：{0}' -f $info.Message) }
        }
    }

    # 兼容统一包装 {data:{token}} 与直返 {token} 两种形态
    $token = $null
    if ($resp.data -and $resp.data.token) { $token = $resp.data.token }
    elseif ($resp.token)                  { $token = $resp.token }

    if ([string]::IsNullOrWhiteSpace($token)) {
        throw '登录成功但响应里没有 token 字段，请检查后端 /api/auth/login 的返回结构'
    }
    return [string]$token
}

# ---------------- Token 预检 ----------------
# 目的：在发起成百上千个请求之前，先确认 token 真的能通过鉴权。
# 起因（真实故障）：一次 2000 请求的压测里有 793 个 401，唯一原因是测试期间
#   该账号在别处登录，后端「顶号下线」递增了 token_version，本脚本手里的
#   token 从那一刻起全部失效（200/401 混合出现）。整轮数据因此没有参考价值。
# 这里用 /api/auth/me（受保护、开销极小）做一次探针，提前暴露问题。
function Test-GipfelAuth {
    param(
        [Parameter(Mandatory)][string]$ServerUrl,
        [Parameter(Mandatory)][string]$Token
    )
    $uri = $ServerUrl.TrimEnd('/') + '/api/auth/me'
    try {
        $resp = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 15 `
                    -Headers @{ Authorization = "Bearer $Token" }
        return @{ Ok = $true; StatusCode = [int]$resp.StatusCode; Message = '' }
    }
    catch {
        $info = Get-GipfelErrorInfo -ErrorRecord $_
        return @{ Ok = $false; StatusCode = $info.StatusCode; Message = $info.Message }
    }
}

function Read-GipfelAuth {
    param(
        [hashtable]$Endpoint,
        [string]$ServerUrl,
        [string]$Token
    )

    $out = @{ Token = ''; User = ''; Pass = ''; TokenSource = '' }
    if ($Token) { $out.Token = $Token; $out.TokenSource = '参数'; }

    # ---- 需要认证的端点：拿 Bearer Token ----
    if ($Endpoint.Auth -and -not $out.Token) {
        Write-Host ''
        Write-Host '此端点需要认证，请选择获取方式:' -ForegroundColor Yellow
        Write-Host '  1. 用账号密码自动登录换取（最省事）'
        Write-Host '  2. 手动粘贴已有 Token'
        Write-Host '  3. 不带认证继续（预期会返回 401）'
        Write-Host ''
        switch ((Read-Host '请选择 (1-3)').Trim()) {
            '1' {
                if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
                    Write-Host '[提示] 自动登录需要服务器地址，请在启动参数里指定 -ServerUrl' -ForegroundColor Red
                } else {
                    Write-Host ''
                    Write-Host '注意：后端登录会「顶号下线」，浏览器里的登录态将立即失效。' -ForegroundColor Yellow
                    $u = (Read-Host '用户名').Trim()
                    if ([string]::IsNullOrWhiteSpace($u)) {
                        Write-Host '[错误] 用户名为空，跳过自动登录' -ForegroundColor Red
                    } else {
                        $p = Read-GipfelSecret -Prompt '密码'
                        $out.User = $u
                        $out.Pass = $p
                        Write-Host '正在登录...' -ForegroundColor Cyan
                        $tok = Get-GipfelToken -ServerUrl $ServerUrl -User $u -Pass $p
                        $out.Token = $tok
                        $out.TokenSource = '自动登录'
                        Write-Host ('[OK] 已获取 Token（{0} 字符）' -f $tok.Length) -ForegroundColor Green
                    }
                }
            }
            '2' {
                Write-Host ''
                Write-Host '获取方法（推荐用第 2 种，最省事）:' -ForegroundColor DarkGray
                Write-Host '  A. 浏览器 F12 -> Console，执行:' -ForegroundColor DarkGray
                Write-Host '       localStorage.getItem(Object.keys(localStorage).find(k=>k.endsWith("__token")))' -ForegroundColor Gray
                Write-Host '     输出的那串（不含首尾引号）就是 Token。' -ForegroundColor DarkGray
                Write-Host '  B. 或 F12 -> Network -> 点开任意 /api/ 请求 ->' -ForegroundColor DarkGray
                Write-Host '       Request Headers -> Authorization: Bearer xxx  (xxx 即 Token)' -ForegroundColor DarkGray
                Write-Host ''
                $t = (Read-Host 'Token').Trim()
                # 容错：用户可能把 "Bearer xxx" 整段或带引号一起粘进来
                $t = $t -replace '^\s*Bearer\s+', ''
                $t = $t.Trim('"').Trim("'").Trim()
                $out.Token = $t
                if ($t) { $out.TokenSource = '手动输入' }
            }
            default {
                Write-Host '[警告] 未提供 Token，本端点很可能返回 401' -ForegroundColor Red
            }
        }
    }

    # ---- POST 登录端点：需要凭据作为被测请求体 ----
    if ($Endpoint.Method -eq 'POST') {
        Write-Host ''
        Write-Host '请输入登录凭据（将作为被测请求的请求体）:' -ForegroundColor Yellow
        if (-not $out.User) { $out.User = (Read-Host '用户名').Trim() }
        if (-not $out.Pass) { $out.Pass = Read-GipfelSecret -Prompt '密码' }
        if ([string]::IsNullOrWhiteSpace($out.User)) {
            Write-Host '[警告] 未提供用户名，测试很可能返回 400' -ForegroundColor Red
        }
    }

    return $out
}

# ---------------- C# 压测内核 ----------------
$script:GipfelLoadCode = @'
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

public class GipfelLoadResult
{
    public int Total, Success, Fail;
    public double Seconds, Rps, Avg;
    public long Min, Max, P50, P95, P99;
    public Dictionary<int, int> Codes = new Dictionary<int, int>();
    // 每个非 2xx 状态码的响应体样本（只取首个）：状态码本身说明不了原因，
    // 例如 401 就可能是「需先改密 / 顶号下线 / 过期」三种完全不同的情况。
    public Dictionary<int, string> Messages = new Dictionary<int, string>();
    public long[] Latencies;
}

public class GipfelLoad
{
    // 进度计数：供 PowerShell 侧轮询显示进度条。
    // 没有它时，慢速端点在长时间内毫无输出，看起来就像卡死。
    public static int ProgressDone;
    public static int ProgressTotal;

    public static Task<GipfelLoadResult> RunAsync(string url, string method, string body, string token,
                                                  int concurrent, int total, int timeoutSec)
    {
        return Task.Run(() => RunCore(url, method, body, token, concurrent, total, timeoutSec));
    }

    // ★ 必须全程 await，不能阻塞线程——这里是上一版卡死的根因：
    //   旧实现用 Task.Run 启动 total 个（可达 2000）任务，并在任务体里
    //   调用阻塞的 sem.Wait()。线程池默认只有约 8~16 个线程，且扩容很慢
    //   （约每 500ms 才加一个），于是线程被「排队等信号量」的任务占满，
    //   真正持证的请求也在同步等待 HTTP 完成，并发数塌陷、进度近乎停滞，
    //   表现为「一直卡在 正在测试...」。
    //   改为 await sem.WaitAsync() + await client.GetAsync() 后，等待期间
    //   线程被还给线程池，既不占线程也不会自我饿死。
    static async Task<GipfelLoadResult> RunCore(string url, string method, string body, string token,
                                                int concurrent, int total, int timeoutSec)
    {
        if (concurrent < 1) concurrent = 1;
        if (total < 1) total = 1;

        var res = new GipfelLoadResult();
        res.Total = total;
        ProgressDone = 0;
        ProgressTotal = total;

        var handler = new HttpClientHandler();
        handler.MaxConnectionsPerServer = concurrent;
        handler.UseCookies = false;

        var client = new HttpClient(handler);
        try
        {
            client.Timeout = TimeSpan.FromSeconds(timeoutSec);
            if (!string.IsNullOrEmpty(token))
            {
                client.DefaultRequestHeaders.Authorization =
                    new AuthenticationHeaderValue("Bearer", token);
            }

            var lat = new ConcurrentBag<long>();
            var codes = new ConcurrentDictionary<int, int>();
            var msgs = new ConcurrentDictionary<int, string>();
            var sem = new SemaphoreSlim(concurrent, concurrent);
            var tasks = new List<Task>(total);
            var swTotal = Stopwatch.StartNew();

            for (int i = 0; i < total; i++)
            {
                // 直接调用 async 方法（不再套 Task.Run）：
                // 它会同步执行到第一个真正的 await 就返回，因此大量待发请求
                // 不会各自占用一个线程池线程。
                tasks.Add(Worker(client, sem, url, method, body, lat, codes, msgs));
            }

            await Task.WhenAll(tasks).ConfigureAwait(false);
            swTotal.Stop();

            res.Seconds = swTotal.Elapsed.TotalSeconds;
            res.Rps = res.Seconds > 0 ? total / res.Seconds : 0;

            // 由状态码分布反推成功/失败，避免在并发路径里维护额外计数器
            int success = 0, fail = 0;
            foreach (var kv in codes)
            {
                res.Codes[kv.Key] = kv.Value;
                if (kv.Key >= 200 && kv.Key < 300) success += kv.Value;
                else fail += kv.Value;
            }
            res.Success = success;
            res.Fail = fail;

            foreach (var kv in msgs) res.Messages[kv.Key] = kv.Value;

            var arr = lat.ToArray();
            Array.Sort(arr);
            res.Latencies = arr;
            if (arr.Length > 0)
            {
                res.Min = arr[0];
                res.Max = arr[arr.Length - 1];
                long sum = 0;
                for (int i = 0; i < arr.Length; i++) sum += arr[i];
                res.Avg = (double)sum / arr.Length;
                res.P50 = arr[(int)Math.Floor(arr.Length * 0.50)];
                res.P95 = arr[(int)Math.Floor(arr.Length * 0.95)];
                int p99i = (int)Math.Floor(arr.Length * 0.99);
                if (p99i > arr.Length - 1) p99i = arr.Length - 1;
                res.P99 = arr[p99i];
            }
            return res;
        }
        finally
        {
            client.Dispose();
            handler.Dispose();
        }
    }

    // 单个请求：从拿许可证到收发完成全程 await，不阻塞任何线程
    static async Task Worker(HttpClient client, SemaphoreSlim sem, string url, string method,
                             string body, ConcurrentBag<long> lat, ConcurrentDictionary<int, int> codes,
                             ConcurrentDictionary<int, string> msgs)
    {
        await sem.WaitAsync().ConfigureAwait(false);
        try
        {
            var sw = Stopwatch.StartNew();
            int code = 0;
            try
            {
                HttpResponseMessage r;
                if (method == "POST")
                {
                    using (var content = new StringContent(body == null ? "" : body,
                                                           Encoding.UTF8, "application/json"))
                    {
                        r = await client.PostAsync(url, content).ConfigureAwait(false);
                    }
                }
                else
                {
                    r = await client.GetAsync(url).ConfigureAwait(false);
                }
                code = (int)r.StatusCode;

                // 只对「每个非 2xx 状态码的第一次出现」抓一次响应体：
                // 状态码本身无法区分原因（401 就有 3 种不同 message），
                // 但每个错误码抓一次就够，不会给压测增加额外负担。
                if ((code < 200 || code >= 300) && !msgs.ContainsKey(code))
                {
                    try
                    {
                        var bodyText = await r.Content.ReadAsStringAsync().ConfigureAwait(false);
                        if (!string.IsNullOrEmpty(bodyText))
                        {
                            if (bodyText.Length > 300) bodyText = bodyText.Substring(0, 300);
                            msgs.TryAdd(code, bodyText);
                        }
                    }
                    catch { }
                }

                r.Dispose();
            }
            catch
            {
                code = 0;   // 0 = 连接失败/超时
            }
            sw.Stop();
            lat.Add(sw.ElapsedMilliseconds);
            codes.AddOrUpdate(code, 1, (k, v) => v + 1);
        }
        finally
        {
            sem.Release();
            Interlocked.Increment(ref ProgressDone);
        }
    }
}
'@

function Initialize-GipfelLoad {
    if ('GipfelLoad' -as [type]) { return }

    # ★ 第一步必须显式加载 System.Net.Http：
    #   Windows PowerShell 5.1 默认**没有**加载该程序集，直接写
    #   [System.Net.Http.HttpClient] 会报 "Unable to find type"。
    try { Add-Type -AssemblyName System.Net.Http -ErrorAction Stop } catch { }

    # 第二步：收集引用路径（动态取 Location，兼容 .NET Framework / .NET Core）。
    #   Add-Type 默认引用集不含 System.Net.Http，必须显式传给 -ReferencedAssemblies，
    #   否则报「命名空间 System.Net 中不存在类型或命名空间名称 Http」。
    $refs = New-Object System.Collections.Generic.List[string]
    foreach ($t in @(
            [System.Net.Http.HttpClient],
            [System.Net.Http.HttpClientHandler],
            [System.Collections.Concurrent.ConcurrentBag[int]],
            [System.Collections.Concurrent.ConcurrentDictionary[int, int]])) {
        try {
            $loc = $t.Assembly.Location
            if ($loc -and -not $refs.Contains($loc)) { [void]$refs.Add($loc) }
        } catch { }
    }
    try {
        Add-Type -TypeDefinition $script:GipfelLoadCode -Language CSharp `
                 -ReferencedAssemblies $refs.ToArray() -ErrorAction Stop
    } catch {
        # 兜底：某些受限环境不接受显式引用，退回默认引用集再试一次
        Add-Type -TypeDefinition $script:GipfelLoadCode -Language CSharp -ErrorAction Stop
    }
}

function Invoke-GipfelLoad {
    param(
        [Parameter(Mandatory)][string]$Url,
        [string]$Method = 'GET',
        [string]$Body = '',
        [string]$Token = '',
        [Parameter(Mandatory)][int]$Concurrent,
        [Parameter(Mandatory)][int]$Total,
        [int]$TimeoutSec = 30
    )
    Initialize-GipfelLoad

    $task = [GipfelLoad]::RunAsync($Url, $Method, $Body, $Token, $Concurrent, $Total, $TimeoutSec)

    # 轮询进度：进度条 + 每 10% 打一行文字。
    # 双管齐下是为了「慢速端点不再被误判为卡死」，也便于把输出重定向到文件后仍能看到进展。
    $lastPct = -1
    $nextMilestone = 10
    while (-not $task.IsCompleted) {
        $done = [GipfelLoad]::ProgressDone
        $tot  = [GipfelLoad]::ProgressTotal
        if ($tot -gt 0) {
            $pct = [int][Math]::Floor(100.0 * $done / $tot)
            if ($pct -ne $lastPct) {
                Write-Progress -Activity '压测进行中' -Status ("{0} / {1} ({2}%)" -f $done, $tot, $pct) `
                               -PercentComplete ([Math]::Min($pct, 100))
                $lastPct = $pct
            }
            if ($pct -ge $nextMilestone) {
                Write-Host ("   进度: {0}/{1} ({2}%)" -f $done, $tot, $pct) -ForegroundColor DarkGray
                # 必须把里程碑推到 pct 之后：并发请求成批完成，pct 会跳跃
                # （如 25 -> 50），只加 10 会导致同一进度被重复打印多次。
                while ($nextMilestone -le $pct) { $nextMilestone += 10 }
            }
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Progress -Activity '压测进行中' -Completed

    # 用 GetAwaiter().GetResult() 而非 .Result：前者抛出原始异常，
    # 后者会裹一层 AggregateException，错误信息对用户不友好。
    return $task.GetAwaiter().GetResult()
}

function New-GipfelLoginBody {
    param([string]$User, [string]$Pass)
    # 用 ConvertTo-Json 避免手工拼串出错（密码含引号/反斜杠时尤其重要）
    return (@{ username = $User; password = $Pass } | ConvertTo-Json -Compress)
}

function Get-GipfelResultDir {
    param([string]$ScriptRoot)
    $dir = Join-Path $ScriptRoot 'test-results'
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    return $dir
}

# 取某个状态码的失败原因（后端统一包装里的 message）。
# 状态码本身分不清原因：401 可能是「需先改密」「顶号下线」「已过期」三种。
function Get-GipfelCodeReason {
    param(
        $Result,
        [int]$Code
    )
    if (-not $Result) { return '' }
    try {
        if (-not $Result.Messages -or -not $Result.Messages.ContainsKey($Code)) { return '' }
        $raw = [string]$Result.Messages[$Code]
        if ([string]::IsNullOrWhiteSpace($raw)) { return '' }
        try {
            $o = $raw | ConvertFrom-Json
            if ($o.message) { return [string]$o.message }
            if ($o.code)    { return ('code=' + $o.code) }
        } catch { }
        return $raw
    } catch {
        return ''
    }
}
