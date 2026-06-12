# Push в GitHub, токен читается из .github-token в корне проекта.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$tokenFile = Join-Path $root ".github-token"

if (-not (Test-Path $tokenFile)) {
    Write-Error "Нет файла .github-token. Скопируйте: copy .github-token.example .github-token"
}

$token = (Get-Content $tokenFile -Raw).Trim()
if (-not $token -or $token -match '^#|^ghp_вставьте') {
    Write-Error "Вставьте реальный токен ghp_... в .github-token (одна строка)"
}

$remote = git -C $root remote get-url origin 2>$null
if (-not $remote) {
    Write-Error "git remote origin не настроен"
}

# https://github.com/USER/REPO.git → push URL с токеном
$pushUrl = $remote -replace '^https://github\.com/', "https://x-access-token:${token}@github.com/"
if ($pushUrl -eq $remote) {
    $pushUrl = $remote -replace '^git@github\.com:', "https://x-access-token:${token}@github.com/"
}

$branch = git -C $root branch --show-current
Write-Host "Pushing $branch -> origin ..."
git -C $root push $pushUrl $branch
git -C $root fetch origin
Write-Host "Done."
