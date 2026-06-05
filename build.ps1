# SteamGifts Bot - Windows single-exe build
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Icon = "$Root\assets\icon.ico"

Set-Location $Root

Write-Host "Installing dependencies..."
pip install -r requirements.txt pyinstaller pillow --quiet

Write-Host "Generating app icon..."
python "$Root\scripts\generate_icon.py"

if (-not (Test-Path $Icon)) {
    throw "Icon not found at $Icon"
}

Write-Host "Building single executable..."
pyinstaller --noconfirm --clean `
    --windowed `
    --onefile `
    --name "SteamGiftsBot" `
    --icon $Icon `
    --add-data "$Icon;assets" `
    --paths "$Root\python" `
    --hidden-import bot `
    --hidden-import gui `
    --hidden-import widgets `
    --hidden-import theme `
    --hidden-import settings `
    --hidden-import paths `
    --hidden-import steamgifts_service `
    --hidden-import http_client `
    --hidden-import windows_startup `
    "$Root\python\main.py"

Write-Host ""
Write-Host "Build complete!"
Write-Host "Executable: $Root\dist\SteamGiftsBot.exe"
Write-Host ""
Write-Host "Place cookie.txt next to the exe before first run."
Write-Host "Settings are stored in %APPDATA%\SteamGiftsBot\settings.json"
