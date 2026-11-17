# Build the upload file for the Manus Cloud Computer.
#   powershell -ExecutionPolicy Bypass -File deploy\cloud\package.ps1
# Result: deploy\cloud\atslab-deploy.tar.gz  (code only: no secrets, no history, no resumes)
#
# Copy that one file to the cloud computer, then follow README-CLOUD.md.

$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$out  = Join-Path $PSScriptRoot "atslab-deploy.tar.gz"
$stage = Join-Path $env:TEMP ("atslab-pack-" + [guid]::NewGuid().ToString("N"))

# Folders and files that must never leave this PC.
# .streamlit is deliberately NOT excluded: config.toml (theme, upload size limit, no file
# watcher) is needed at runtime. Only .streamlit/secrets.toml is excluded, by name, below.
$excludeDirs = @(
  ".git", ".work", "outputs", "data", "deploy", "golden_extra", "__pycache__",
  "release-1.5", "pretest_public", "jdtest_public", "jdtest_tools",
  "cv_reviews", "dashboard_jobs", "reports", "CV2", "CV3", "CV4", "CVS",
  "JobDe", "testcvs", "strongcvs", "weakcvs", "competitorcvs", "shikhatest",
  "tariqtest", "nextsteps-resumes", "aiApply.cvs", "calib_work", "sidebar_check"
)
$excludeFiles = @("*.log", "*.csv", "*.bat", "*.ico", "results_*.json", "*.pyc", "secrets.toml")
$excludeNested = @(".streamlit\secrets.toml", "deploy\cloud\.env", "deploy\cloud\atslab-deploy.tar.gz")

Write-Host "Packaging from $root"
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$robocopyArgs = @($root, $stage, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np", "/XD")
$robocopyArgs += $excludeDirs
$robocopyArgs += @("/XF")
$robocopyArgs += $excludeFiles
& robocopy @robocopyArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

# The Cloud Computer bundle itself is copied back in on purpose: it is the install script.
New-Item -ItemType Directory -Force -Path (Join-Path $stage "deploy\cloud") | Out-Null
Copy-Item "$PSScriptRoot\*" (Join-Path $stage "deploy\cloud") -Recurse -Force

# Trim what the app never needs at runtime: old frozen releases, packed test sets and
# session folders. They only make the upload bigger.
foreach ($pattern in @("release-v*", "design_check_v*", "calib_huntr", "riyaj-portfolio", ".manus")) {
  Get-ChildItem -Path $stage -Filter $pattern -Directory -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
foreach ($pattern in @("nextsteps-resumes.zip", "*.pyc")) {
  Get-ChildItem -Path $stage -Filter $pattern -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
}

# Never ship a filled-in .env or a secrets file, only the examples.
foreach ($rel in $excludeNested) {
  Remove-Item (Join-Path $stage $rel) -Force -ErrorAction SilentlyContinue
}

# Fail loudly if a secret ever made it into the package.
$leak = Get-ChildItem -Path $stage -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -eq "secrets.toml" -or $_.Name -eq ".env" }
if ($leak) {
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
  throw "refusing to package: found $($leak.FullName -join ', ')"
}

if (-not (Test-Path (Join-Path $stage ".streamlit\config.toml"))) {
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
  throw "refusing to package: .streamlit/config.toml is missing"
}

if (Test-Path $out) { Remove-Item $out -Force }
& tar -czf $out -C $stage .
if ($LASTEXITCODE -ne 0) { throw "tar failed" }
Remove-Item $stage -Recurse -Force

$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host ""
Write-Host "Created: $out  ($size MB)"
Write-Host "Next: copy it to the cloud computer, then follow deploy/cloud/README-CLOUD.md"
