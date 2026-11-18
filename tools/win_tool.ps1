# Run one of the bash tools on Windows: sets up the MSVC developer environment (x64), then runs the
# script in Git Bash. Docs: docs/notes/windows.md
#
#   tools\win build --rom tr            = tools/build.sh --rom tr
#   tools\win run --rom tr              = tools/run.sh --rom tr
#   tools\win recompiler_update sync    = tools/recompiler_update.sh sync
#   tools\win release_windows           = tools/release_windows.sh
#   tools\win bash                      an interactive Git Bash with the MSVC environment
#
# tools\win.cmd calls this file with "-ExecutionPolicy Bypass", so no policy has to be changed.
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Tool,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 1. Visual Studio 2022 (Build Tools or any edition) with the C++ workload, found by vswhere.
if (-not $env:VCINSTALLDIR) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found: install Visual Studio 2022 Build Tools (docs/notes/windows.md)." }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { throw "No Visual Studio with the C++ tools (workload 'Desktop development with C++')." }
    $devshell = Join-Path $vs 'Common7\Tools\Launch-VsDevShell.ps1'
    & $devshell -Arch amd64 -HostArch amd64 -SkipAutomaticLocation | Out-Null
}
foreach ($t in 'cl', 'cmake', 'ninja') {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t not found after the developer environment was set up." }
}

# 2. Git Bash (Git for Windows): bash, patch, diff, find, sha256sum for the tools/*.sh scripts.
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { throw "git not found: install Git for Windows." }
$bash = Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) 'bin\bash.exe'
if (-not (Test-Path $bash)) { $bash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe' }
if (-not (Test-Path $bash)) { throw "Git Bash not found (expected next to git.exe)." }

# 3. Python 3.11+ (tomllib) as "python".
if (-not $env:PYTHON) {
    if (Get-Command python -ErrorAction SilentlyContinue) { $env:PYTHON = 'python' }
    else { throw "python not found: install Python 3.11 or newer (python.org, 'Add to PATH')." }
}

if ($Tool -eq 'bash') {
    & $bash --login -i
    exit $LASTEXITCODE
}
$script = Join-Path $root "tools\$Tool"
if (-not $Tool.EndsWith('.sh')) { $script = "$script.sh" }
if (-not (Test-Path $script)) { throw "No such tool: $script" }
& $bash $script.Replace('\', '/') @Rest
exit $LASTEXITCODE
