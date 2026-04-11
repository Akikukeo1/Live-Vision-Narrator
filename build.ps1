<#
build.ps1 - Windows build helper for Live-Vision-Narrator

Usage:
  .\build.ps1 -Build             # build Go binary into bin\narrator_engine.exe
  .\build.ps1 -Clean             # remove bin artifacts
  .\build.ps1 -Test              # run `go test` in src-go
  .\build.ps1 -Run               # build then run
  .\build.ps1 -Cross -OS linux   # cross-build for linux (requires Go env configured)
#>

param(
    [switch]$Build,
    [switch]$Clean,
    [switch]$Test,
    [switch]$Run,
    [switch]$Cross,
    [string]$OS = 'linux'
)

Set-StrictMode -Version Latest
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

if ($Clean) {
    Write-Host "Cleaning bin/ artifacts..."
    Remove-Item -Force -ErrorAction SilentlyContinue "$root\bin\narrator_engine.exe"
    Remove-Item -Force -ErrorAction SilentlyContinue "$root\bin\narrator_engine_linux"
    exit 0
}

if ($Test) {
    Write-Host "Running Go tests in src-go/..."
    Push-Location "$root\src-go"
    & go test -v ./...
    $code = $LASTEXITCODE
    Pop-Location
    exit $code
}

if ($Cross) {
    if ($OS -eq 'linux') {
        Write-Host "Cross-compiling Linux x86_64..."
        & go build -o "$root\bin\narrator_engine_linux" ./src-go
        exit $LASTEXITCODE
    } elseif ($OS -eq 'windows') {
        Write-Host "Cross-compiling Windows x86_64..."
        & go build -o "$root\bin\narrator_engine.exe" ./src-go
        exit $LASTEXITCODE
    } else {
        Write-Error "Unsupported OS: $OS"
        exit 2
    }
}

if ($Build -or $Run) {
    Write-Host "Building Go binary into bin\\narrator_engine.exe"
    if (-not (Test-Path "$root\bin")) { New-Item -ItemType Directory -Path "$root\bin" | Out-Null }
    & go build -o "$root\bin\narrator_engine.exe" ./src-go
    if ($LASTEXITCODE -ne 0) { Write-Error "go build failed"; exit $LASTEXITCODE }
}

if ($Run) {
    Write-Host "Running bin\\narrator_engine.exe"
    & "$root\bin\narrator_engine.exe"
}

exit 0
