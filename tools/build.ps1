#requires -Version 5.1
<#
.SYNOPSIS
    打包 Edge 扩展（薄封装，实际逻辑在 tools/build.js）。

.DESCRIPTION
    产出：
      dist/json-formatter-pro-<版本>.zip  可直接上传 Edge 加载项商店
      dist/unpacked/                      可直接被浏览器加载的干净副本

    条目名统一使用正斜杠，符合 ZIP 规范；OpenAI 之上无依赖，只需 Node.js 18+。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools/build.ps1
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Find-Node {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "${env:ProgramFiles(x86)}\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe"
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    $base = Join-Path $env:USERPROFILE '.workbuddy\binaries\node\versions'
    if (Test-Path $base) {
        $found = Get-ChildItem $base -Filter node.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$node = Find-Node
if (-not $node) { throw '未找到 node，请先安装 Node.js 18+ 再运行本脚本。' }

& $node (Join-Path $PSScriptRoot 'build.js')
exit $LASTEXITCODE
