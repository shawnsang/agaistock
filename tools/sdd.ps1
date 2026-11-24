<#
.SYNOPSIS
  Subagent-Driven Development 的本地助手（PowerShell 版）。

.DESCRIPTION
  上游 skill 的 scripts/{sdd-workspace,task-brief,review-package} 是 bash 脚本，
  但本机没有可用的 WSL /bin/bash，因此提供等价的 PowerShell 实现。
  行为与上游脚本保持一致：
    - sdd-workspace   → 解析并创建本计划的 SDD 工作目录，打印其绝对路径
    - task-brief      → 把某个 Task 的完整文本抽成独立文件，供实现者一次性读取
    - review-package  → 生成 commit 列表 + 变更统计 + 完整 diff 的评审包

.EXAMPLE
  pwsh -File tools/sdd.ps1 workspace <plan.md>
  pwsh -File tools/sdd.ps1 brief <plan.md> 3
  pwsh -File tools/sdd.ps1 package <plan.md> <base> <head>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('workspace', 'brief', 'package')]
    [string]$Command,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$PlanFile,

    [Parameter(Position = 2)]
    [string]$Arg3,

    [Parameter(Position = 3)]
    [string]$Arg4,

    [Parameter(Position = 4)]
    [string]$Arg5
)

$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    $root = git rev-parse --show-toplevel 2>$null
    if (-not $root) { throw '当前目录不是 git 仓库' }
    return $root.Trim()
}

function Get-SddWorkspace([string]$planPath) {
    $resolved = (Resolve-Path $planPath).Path
    $slug = [System.IO.Path]::GetFileNameWithoutExtension($resolved)
    if (-not $slug -or $slug -eq '.' -or $slug -eq '..') {
        throw "无法从 $planPath 推导工作区名"
    }
    $base = Join-Path (Get-RepoRoot) '.superpowers\sdd'
    $dir = Join-Path $base $slug
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Content -Path (Join-Path $base '.gitignore') -Value '*' -Encoding UTF8 -NoNewline
    Add-Content -Path (Join-Path $base '.gitignore') -Value "`n" -Encoding UTF8 -NoNewline
    return $dir
}

switch ($Command) {
    'workspace' {
        Get-SddWorkspace $PlanFile
        break
    }

    'brief' {
        if (-not $Arg3) { throw '用法: sdd.ps1 brief <plan.md> <task-number> [outfile]' }
        $taskNumber = [int]$Arg3
        $dir = Get-SddWorkspace $PlanFile
        $out = if ($Arg4) { $Arg4 } else { Join-Path $dir "task-$taskNumber-brief.md" }

        $lines = [System.IO.File]::ReadAllLines((Resolve-Path $PlanFile).Path)
        $headingPattern = '^#+\s+Task\s+(\d+)([^\d]|$)'
        $start = -1
        $end = $lines.Count
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match $headingPattern) {
                $n = [int]$matches[1]
                if ($n -eq $taskNumber -and $start -lt 0) {
                    $start = $i
                }
                elseif ($n -ne $taskNumber -and $start -ge 0 -and $i -gt $start) {
                    $end = $i
                    break
                }
            }
        }
        if ($start -lt 0) {
            throw "在计划中找不到 Task $taskNumber"
        }
        $body = $lines[$start..($end - 1)]
        [System.IO.File]::WriteAllLines($out, $body, (New-Object System.Text.UTF8Encoding($false)))
        Write-Output "wrote ${out}: $($body.Count) lines"
        break
    }

    'package' {
        if (-not $Arg3 -or -not $Arg4) { throw '用法: sdd.ps1 package <plan.md> <base> <head> [outfile]' }
        $base = $Arg3
        $head = $Arg4
        git rev-parse --verify --quiet $base | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "bad BASE: $base" }
        git rev-parse --verify --quiet $head | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "bad HEAD: $head" }

        $dir = Get-SddWorkspace $PlanFile
        $shortBase = (git rev-parse --short $base).Trim()
        $shortHead = (git rev-parse --short $head).Trim()
        $out = if ($Arg5) { $Arg5 } else { Join-Path $dir "review-${shortBase}..${shortHead}.diff" }

        $sb = New-Object System.Text.StringBuilder
        [void]$sb.AppendLine("# Review package: ${base}..${head}")
        [void]$sb.AppendLine()
        [void]$sb.AppendLine('## Commits')
        [void]$sb.AppendLine((git log --oneline "${base}..${head}" | Out-String).TrimEnd())
        [void]$sb.AppendLine()
        [void]$sb.AppendLine('## Files changed')
        [void]$sb.AppendLine((git diff --stat "${base}..${head}" | Out-String).TrimEnd())
        [void]$sb.AppendLine()
        [void]$sb.AppendLine('## Diff')
        [void]$sb.AppendLine((git diff -U10 "${base}..${head}" | Out-String))
        [System.IO.File]::WriteAllText($out, $sb.ToString(), (New-Object System.Text.UTF8Encoding($false)))

        $commits = (git rev-list --count "${base}..${head}").Trim()
        $bytes = (Get-Item $out).Length
        Write-Output "wrote ${out}: $commits commit(s), $bytes bytes"
        break
    }
}
