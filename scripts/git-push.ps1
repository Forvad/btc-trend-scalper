# Push to GitHub; token is read from .github-token in project root.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$tokenFile = Join-Path $root ".github-token"

if (-not (Test-Path $tokenFile)) {
    Write-Error "Missing .github-token. Copy: copy .github-token.example .github-token"
}

$token = (Get-Content $tokenFile -Raw).Trim()
if (-not $token -or $token.StartsWith("#") -or $token -like "*вставьте*") {
    Write-Error "Put a real ghp_ token in .github-token (single line)"
}

$remote = git -C $root remote get-url origin 2>$null
if (-not $remote) {
    Write-Error "git remote origin is not configured"
}

$pushUrl = $remote
if ($remote -match '^https://github\.com/') {
    $pushUrl = $remote -replace '^https://github\.com/', "https://x-access-token:${token}@github.com/"
} elseif ($remote -match '^git@github\.com:') {
    $pushUrl = $remote -replace '^git@github\.com:', "https://x-access-token:${token}@github.com/"
}

$branch = git -C $root branch --show-current
Write-Host "Pushing $branch to origin..."
git -C $root push $pushUrl $branch
git -C $root fetch origin
Write-Host "Done."
