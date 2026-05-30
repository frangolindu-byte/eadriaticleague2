param(
    [string]$Message = "Atualizacao automatica do dashboard"
)

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$dataJson = Join-Path $projectDir "docs\data.json"
$indexHtml = Join-Path $projectDir "docs\index.html"

if (-not (Test-Path $dataJson)) {
    Write-Host "ERRO: docs/data.json nao encontrado. Execute o robo primeiro." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $indexHtml)) {
    Write-Host "ERRO: docs/index.html nao encontrado." -ForegroundColor Red
    exit 1
}

Write-Host "Deploy para GitHub Pages..." -ForegroundColor Cyan
Set-Location $projectDir

git add docs/index.html docs/data.json
git commit -m $Message
git push

if ($LASTEXITCODE -eq 0) {
    Write-Host "Deploy concluido!" -ForegroundColor Green
    Write-Host "Acesse: https://<seu-usuario>.github.io/<seu-repo>/" -ForegroundColor Yellow
} else {
    Write-Host "ERRO no deploy." -ForegroundColor Red
    exit 1
}
