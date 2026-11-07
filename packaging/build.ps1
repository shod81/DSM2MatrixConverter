#Requires -Version 5.1
<#
.SYNOPSIS
    Build the Dsm2Empirum single-EXE distribution (Task T-100).

.DESCRIPTION
    Steps: install build requirements, run the test suite as a quality gate
    (project rule 9), run PyInstaller with packaging/dsm2emp.spec, and smoke
    test the resulting CLI executable (AK-5: selftest must exit 0).

    Output:  packaging\dist\Dsm2Empirum.exe     (GUI, windowed)
             packaging\dist\Dsm2EmpirumCmd.exe  (CLI, console)

.PARAMETER SkipTests
    Skip the pytest gate (NOT recommended; required for a release build).

.PARAMETER SkipSmokeTest
    Skip the Dsm2EmpirumCmd.exe selftest / --version smoke test.

.EXAMPLE
    .\packaging\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = "Stop"

$packagingDir = $PSScriptRoot
$repoRoot = Split-Path -Parent $packagingDir

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }
Write-Host "[1/4] Using Python: $python"

Write-Host "[2/4] Installing build requirements (editable + dev/gui extras)..."
& $python -m pip install -e "$repoRoot[dev,gui]" --disable-pip-version-check --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)." }

if ($SkipTests) {
    Write-Warning "[3/4] SKIPPING test suite (-SkipTests). Do not ship this build."
} else {
    Write-Host "[3/4] Running test suite (quality gate, project rule 9)..."
    & $python -m pytest --tb=short
    if ($LASTEXITCODE -ne 0) { throw "Test suite failed (exit $LASTEXITCODE) - build aborted." }
}

Write-Host "[4/4] Running PyInstaller..."
Push-Location $packagingDir
try {
    & $python -m PyInstaller --clean --noconfirm dsm2emp.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}

$guiExe = Join-Path $packagingDir "dist\Dsm2Empirum.exe"
$cmdExe = Join-Path $packagingDir "dist\Dsm2EmpirumCmd.exe"
foreach ($exe in @($guiExe, $cmdExe)) {
    if (-not (Test-Path $exe)) { throw "Expected output missing: $exe" }
}

# Keep root dist/ in sync if present to prevent stale binary execution
$rootDist = Join-Path $repoRoot "dist"
if (Test-Path $rootDist) {
    Copy-Item $guiExe, $cmdExe $rootDist -Force
}

if (-not $SkipSmokeTest) {
    Write-Host "Smoke test: Dsm2EmpirumCmd.exe --version ..."
    & $cmdExe --version
    if ($LASTEXITCODE -ne 0) { throw "Version smoke test failed (exit $LASTEXITCODE)." }

    Write-Host "Smoke test: Dsm2EmpirumCmd.exe selftest (AK-5) ..."
    & $cmdExe selftest
    if ($LASTEXITCODE -ne 0) { throw "Selftest smoke test failed (exit $LASTEXITCODE)." }
}

Write-Host ""
Write-Host "Build OK:"
Get-Item $guiExe, $cmdExe | ForEach-Object {
    Write-Host ("  {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB))
}
Write-Host ""
Write-Host "AV note (R-08/R-09): built without UPX; for distribution use code"
Write-Host "signing and see docs\BUILD.md for the false-positive submission recipe."
