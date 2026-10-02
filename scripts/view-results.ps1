# ============================================================
#  Gipfel 测试结果查看工具
#  用法: 双击 scripts\view-results.bat
#        powershell -ExecutionPolicy Bypass -File scripts\view-results.ps1
# ============================================================
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$resultDir = Join-Path $PSScriptRoot 'test-results'

function Show-ReportDetail {
    param([string]$Path)

    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    测试报告'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object { Write-Host ("  {0}" -f $_) }

    $csv = [System.IO.Path]::ChangeExtension($Path, '.csv')
    if (-not (Test-Path -LiteralPath $csv)) { return }

    $rows = Import-Csv -LiteralPath $csv -Encoding UTF8
    if (-not $rows -or $rows.Count -eq 0) { return }

    $times = $rows | ForEach-Object { [int]$_.'响应时间ms' }
    $sorted = $times | Sort-Object
    $n = $sorted.Count
    $total = ($times | Measure-Object -Sum).Sum

    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    明细分析 (CSV)'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    Write-Host ("  样本数: {0}" -f $n)
    Write-Host ("  最小值: {0} ms" -f $sorted[0])
    Write-Host ("  最大值: {0} ms" -f $sorted[-1])
    Write-Host ("  平均值: {0} ms" -f [Math]::Round(($total / $n), 2))
    Write-Host ''
    Write-Host '  响应时间分布:' -ForegroundColor Yellow

    $buckets = [ordered]@{
        '0-100ms'    = 0
        '100-200ms'  = 0
        '200-500ms'  = 0
        '500-1000ms' = 0
        '1000-2000ms'= 0
        '>2000ms'    = 0
    }
    foreach ($t in $times) {
        if     ($t -lt 100)  { $buckets['0-100ms']++ }
        elseif ($t -lt 200)  { $buckets['100-200ms']++ }
        elseif ($t -lt 500)  { $buckets['200-500ms']++ }
        elseif ($t -lt 1000) { $buckets['500-1000ms']++ }
        elseif ($t -lt 2000) { $buckets['1000-2000ms']++ }
        else                 { $buckets['>2000ms']++ }
    }
    foreach ($k in $buckets.Keys) {
        $v   = $buckets[$k]
        $pct = [Math]::Round($v / $n * 100, 1)
        $bar = '#' * [Math]::Min([int][Math]::Floor($v / $n * 50), 50)
        Write-Host ("   {0,-12} {1,6}  ({2,5}%)  {3}" -f $k, $v, $pct, $bar)
    }
    Write-Host ''
}

try {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '  Gipfel 测试结果查看工具'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''

    if (-not (Test-Path -LiteralPath $resultDir)) {
        throw ("未找到测试结果目录: {0}`n请先运行 stress-test.bat 或 quick-test.bat" -f $resultDir)
    }

    $files = @(Get-ChildItem -LiteralPath $resultDir -Filter '*.txt' -File |
               Sort-Object LastWriteTime -Descending)
    if ($files.Count -eq 0) {
        throw ("未找到测试报告（*.txt）: {0}" -f $resultDir)
    }

    Write-Host '可用的测试结果（新 -> 旧）:' -ForegroundColor Yellow
    Write-Host ''
    for ($i = 0; $i -lt $files.Count; $i++) {
        Write-Host ("  {0,2}. {1}   {2}" -f ($i + 1), $files[$i].Name,
                    $files[$i].LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
    }
    Write-Host ''

    $sel = (Read-Host ("请选择要查看的结果 (1-{0}，回车取消)" -f $files.Count)).Trim()
    if ([string]::IsNullOrWhiteSpace($sel)) { return }
    $idx = 0
    if (-not [int]::TryParse($sel, [ref]$idx) -or $idx -lt 1 -or $idx -gt $files.Count) {
        throw '无效选择'
    }
    $chosen = $files[$idx - 1]

    Show-ReportDetail -Path $chosen.FullName

    Write-Host '操作:' -ForegroundColor Yellow
    Write-Host '  1. 用记事本打开报告'
    Write-Host '  2. 用 Excel 打开 CSV 明细'
    Write-Host '  3. 打开结果目录'
    Write-Host '  4. 退出'
    Write-Host ''
    switch ((Read-Host '请选择操作 (1-4)').Trim()) {
        '1' { Start-Process notepad.exe -ArgumentList ('"{0}"' -f $chosen.FullName) }
        '2' {
            $csv = [System.IO.Path]::ChangeExtension($chosen.FullName, '.csv')
            if (Test-Path -LiteralPath $csv) { Start-Process -FilePath $csv }
            else { Write-Host 'CSV 文件不存在' -ForegroundColor Red }
        }
        '3' { Start-Process -FilePath explorer.exe -ArgumentList ('"{0}"' -f $resultDir) }
        default { }
    }
}
catch {
    Write-Host ''
    Write-Host ('[错误] ' + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ''
    [void](Read-Host '按回车退出')
}
