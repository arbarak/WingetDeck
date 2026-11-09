# Builds the portable exe into dist\<date>\. Earlier builds are never overwritten.
#   scripts\build.ps1            x64, using .venv
#   scripts\build.ps1 -Arch x86  x86, using .venv-x86 (a 32-bit Python 3.12 without pywinpty)
param(
    [ValidateSet("x64", "x86")] [string] $Arch = "x64",
    [int] $MinFreeGB = 1
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$freeGB = (Get-PSDrive ($root.Substring(0, 1))).Free / 1GB
if ($freeGB -lt $MinFreeGB) {
    throw ("Only {0:N1} GB free; the build needs at least {1} GB." -f $freeGB, $MinFreeGB)
}

$python = if ($Arch -eq "x64") { ".venv\Scripts\python.exe" } else { ".venv-x86\Scripts\python.exe" }
if (-not (Test-Path $python)) {
    throw "$python not found. See the README, Building section."
}

if (-not (Test-Path "assets\wingetdeck.ico")) {
    & $python "scripts\make_icon.py" "assets\wingetdeck.ico"
    if ($LASTEXITCODE) { throw "The icon could not be made." }
}

$version = (& $python -c "import sys; sys.path.insert(0, 'src'); import wingetdeck; print(wingetdeck.__version__)").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Could not read the version: $version" }

$date = Get-Date -Format "yyyy-MM-dd"
$folder = "dist\$date"
$name = "WingetDeck-$version-$Arch"  # what people download, so it says which version and which processor
if (Test-Path "$folder\$name.exe") {
    $folder = "dist\$date\" + (Get-Date -Format "HHmmss")
}
New-Item -ItemType Directory -Force $folder | Out-Null

$env:WINGETDECK_EXE_NAME = $name
& $python -m PyInstaller --noconfirm --clean --distpath $folder --workpath "build\$Arch" "wingetdeck.spec"
if ($LASTEXITCODE) { throw "PyInstaller failed." }

$exe = Join-Path $folder "$name.exe"
& $exe --version
if ($LASTEXITCODE) { throw "The built exe did not run." }
"Built $exe ({0:N1} MB)" -f ((Get-Item $exe).Length / 1MB)
