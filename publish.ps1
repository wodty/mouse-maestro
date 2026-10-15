#!/usr/bin/env pwsh
# 一键发布到 GitHub
# 用法: .\publish.ps1

$ErrorActionPreference = "Stop"
$RepoName = "mouse-maestro"

# 1. 找 gh CLI
$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    $localGh = Join-Path $PSScriptRoot "..\gh_tmp\bin\gh.exe"
    if (Test-Path $localGh) {
        $gh = Get-Command $localGh
    } else {
        Write-Host "❌ 未找到 gh CLI。请安装 GitHub CLI: https://cli.github.com/" -ForegroundColor Red
        exit 1
    }
}

# 2. 检查登录状态
$auth = & $gh.Source auth status 2>&1
if ($auth -match "not logged") {
    Write-Host "🔐 尚未登录 GitHub，正在启动浏览器授权..." -ForegroundColor Yellow
    & $gh.Source auth login --git-protocol https --web
    Write-Host "授权完成后请重新运行本脚本。" -ForegroundColor Green
    exit 0
}

# 3. 确保当前目录是 git 仓库
if (-not (Test-Path ".git")) {
    git init
    git add .
    git commit -m "feat: v1.0.0 初始发布"
}

# 4. 创建远程仓库（如果不存在）并推送
$remotes = git remote
if ($remotes -notcontains "origin") {
    Write-Host "📦 创建 GitHub 仓库 wodty/$RepoName ..." -ForegroundColor Cyan
    & $gh.Source repo create $RepoName --public --source=. --remote=origin --push
} else {
    Write-Host "🚀 推送到 origin ..." -ForegroundColor Cyan
    git push -u origin main
}

# 5. 创建 Release 并上传 exe
$exe = Join-Path $PSScriptRoot "鼠标编排师.exe"
if (Test-Path $exe) {
    Write-Host "🚀 创建 Release v1.0.0 并上传 exe ..." -ForegroundColor Cyan
    & $gh.Source release create "v1.0.0" --title "鼠标编排师 v1.0.0" --notes-file CHANGELOG.md "$exe"
} else {
    Write-Host "⚠️ 未找到 鼠标编排师.exe，跳过 Release 附件上传。" -ForegroundColor Yellow
}

Write-Host "✅ 完成！访问 https://github.com/wodty/$RepoName/releases" -ForegroundColor Green
