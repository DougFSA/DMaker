# Bootstrap do DMaker: venv + pacote + FFmpeg + Poppins, tudo dentro da pasta do projeto.
# Uso: .\scripts\setup.ps1   (PowerShell, na raiz do projeto)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) {
    Write-Host "Criando .venv..."
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { py -3 -m venv .venv } else { python -m venv .venv }
}

Write-Host "Instalando o dmaker e dependências..."
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".\.venv\Scripts\python.exe" -m pip install -e ".[dev,captions]" --quiet

Write-Host "Baixando FFmpeg e fontes (se necessário)..."
& ".\.venv\Scripts\dmaker.exe" setup

Write-Host ""
& ".\.venv\Scripts\dmaker.exe" doctor
Write-Host ""
Write-Host "Pronto. Use: .\.venv\Scripts\dmaker.exe --help"
