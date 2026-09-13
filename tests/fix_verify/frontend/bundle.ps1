# Frontend bundle helper (verification only).
#
# Bundles one entry file into a single ESM file with the esbuild CLI so Node can
# import REAL frontend source (stores / api layer) instead of a copy of the logic.
# Browser-only deps are redirected with --alias to tests/fix_verify/frontend/stubs/.
#
# Why the CLI instead of the esbuild JS API: the JS API talks to its service
# process over piped stdio, which this sandbox denies (EPERM); the CLI runs the
# native binary with inherited stdio and works.
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less scripts
# with the ANSI code page, and non-ASCII text can corrupt the parse.
#
# Usage (from the repository root):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\fix_verify\frontend\bundle.ps1 -Entry <entry> -Outfile <out>
param(
  [Parameter(Mandatory = $true)][string]$Entry,
  [Parameter(Mandatory = $true)][string]$Outfile
)

$ErrorActionPreference = 'Stop'

$here = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $here '..\..\..')).Path
$frontendDir = Join-Path $repoRoot 'frontend'
$esbuild = Join-Path $frontendDir 'node_modules\@esbuild\win32-x64\esbuild.exe'
if (-not (Test-Path $esbuild)) { throw "esbuild binary not found: $esbuild" }

$srcDir = Join-Path $frontendDir 'src'
$stubDir = Join-Path $here 'stubs'
$entryPath = (Resolve-Path $Entry).Path
$outPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Outfile))

# The entry lives under tests/, so a bare "pinia" import cannot walk up to
# frontend/node_modules. Alias it to that single ESM build: aliases are global,
# so frontend/src gets the same file too (two pinia instances would break
# setActivePinia).
$piniaEsm = Join-Path $frontendDir 'node_modules\pinia\dist\pinia.esm-browser.js'
if (-not (Test-Path $piniaEsm)) { throw "pinia esm build not found: $piniaEsm" }

$esbuildArgs = @(
  $entryPath
  "--outfile=$outPath"
  '--bundle'
  '--format=esm'
  '--platform=browser'
  '--target=es2022'
  '--log-level=warning'
  "--alias:@=$srcDir"
  "--alias:pinia=$piniaEsm"
  "--alias:element-plus=$(Join-Path $stubDir 'element-plus.mjs')"
  # Quotes inside a define value must be written as \" to survive the trip
  # through the native command line.
  '--define:import.meta.env.MODE=\"test\"'
  '--define:import.meta.env.DEV=false'
  '--define:import.meta.env.PROD=true'
  '--define:import.meta.env.BASE_URL=\"/\"'
  '--define:import.meta.env.VITE_API_BASE_URL=\"\"'
)

& $esbuild @esbuildArgs
$code = $LASTEXITCODE
if ($code -ne 0) { throw "esbuild failed, exit code $code" }

Write-Host "bundled $Entry -> $outPath"
