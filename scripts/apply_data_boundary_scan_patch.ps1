# Apply data-boundary scan files from the PR package into the OpenJarvis repo.
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts/apply_data_boundary_scan_patch.ps1 -PackageDir C:\path\to\openjarvis_data_boundary_scan_pr_package_v5

param(
    [string]$PackageDir = (Join-Path $PSScriptRoot "..\..\Downloads\openjarvis_data_boundary_scan_pr_package_v5")
)

$ErrorActionPreference = "Stop"
$RepoDir = (Get-Location).Path

$required = @(
    "pyproject.toml",
    "src\openjarvis\cli\scan_cmd.py",
    "src\openjarvis\cli\__init__.py"
)
foreach ($item in $required) {
    if (-not (Test-Path (Join-Path $RepoDir $item))) {
        throw "Expected to run from the OpenJarvis repository root; missing $item"
    }
}

$NewFiles = Join-Path $PackageDir "new_files"
if (-not (Test-Path $NewFiles)) {
    throw "Package new_files directory not found: $NewFiles"
}

$dirs = @(
    "src\openjarvis\security",
    "tests\security",
    "tests\cli",
    "docs\user-guide",
    "scripts"
)
foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Force -Path (Join-Path $RepoDir $dir) | Out-Null
}

$copyMap = @{
    "src\openjarvis\security\data_boundary_audit.py" = "src\openjarvis\security\data_boundary_audit.py"
    "src\openjarvis\cli\scan_cmd.py" = "src\openjarvis\cli\scan_cmd.py"
    "src\openjarvis\cli\__init__.py" = "src\openjarvis\cli\__init__.py"
    "tests\security\test_data_boundary_audit.py" = "tests\security\test_data_boundary_audit.py"
    "tests\cli\test_scan_data_boundaries.py" = "tests\cli\test_scan_data_boundaries.py"
    "docs\user-guide\data-boundary-scan.md" = "docs\user-guide\data-boundary-scan.md"
}

foreach ($entry in $copyMap.GetEnumerator()) {
    $source = Join-Path $NewFiles $entry.Key
    $dest = Join-Path $RepoDir $entry.Value
    Copy-Item -Path $source -Destination $dest -Force
}

Write-Host "Applied data-boundary scan files from package."
Write-Host "Note: mkdocs.yml nav entry and security.md cross-link must be merged manually if not already present."
Write-Host "Inspect with: git diff"
