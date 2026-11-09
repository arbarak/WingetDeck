# Runs inside Windows Sandbox, called by setup_and_run.ps1: is each exe in C:\dist really portable on a PC
# with no Python? Start it with: python scripts\sandbox\make_wsb.py smoke, then open the .wsb it writes.
# Put the exes to test in dist-sandbox\ first.
param([string]$Out = "C:\out\smoke")

$results = @()

function Add-Result([string]$Exe, [string]$Check, [bool]$Ok, [string]$Detail = "") {
    $script:results += [pscustomobject]@{ exe = $Exe; check = $Check; ok = $Ok; detail = $Detail }
}

function Start-Demo([string]$Path, [string]$Folder) {
    $process = Start-Process -FilePath $Path -ArgumentList "--demo" -WorkingDirectory $Folder -PassThru
    Start-Sleep 15
    $alive = -not $process.HasExited
    if ($alive) { Stop-Process -Id $process.Id -Force }
    return $alive
}

foreach ($source in Get-ChildItem "C:\dist\*.exe") {
    $name = $source.Name
    $folder = "C:\Program Tést été"
    New-Item -ItemType Directory -Force $folder | Out-Null
    $exe = Join-Path $folder $name
    Copy-Item $source.FullName $exe -Force

    $version = & $exe --version
    Add-Result $name "--version exits 0" ($LASTEXITCODE -eq 0) "$version"
    Add-Result $name "demo stays running" (Start-Demo $exe $folder)
    Add-Result $name "WingetDeck-data beside the exe" (Test-Path (Join-Path $folder "WingetDeck-data\demo\logs"))

    $locked = "C:\Locked $($source.BaseName)"
    New-Item -ItemType Directory -Force $locked | Out-Null
    $exe2 = Join-Path $locked $name
    Copy-Item $source.FullName $exe2 -Force
    & icacls $locked /deny "$($env:USERNAME):(OI)(CI)(WD,AD)" | Out-Null
    Add-Result $name "demo stays running from a read-only folder" (Start-Demo $exe2 $locked)
    Add-Result $name "data falls back to the profile" (Test-Path "$env:LOCALAPPDATA\WingetDeck\demo\logs")
    & icacls $locked /remove:d $env:USERNAME | Out-Null
    Remove-Item "$env:LOCALAPPDATA\WingetDeck" -Recurse -Force -ErrorAction SilentlyContinue
}

$results | ConvertTo-Json | Out-File "$Out\smoke.json" -Encoding utf8
$results | Format-Table -AutoSize | Out-String | Out-File "$Out\smoke.txt" -Encoding utf8
