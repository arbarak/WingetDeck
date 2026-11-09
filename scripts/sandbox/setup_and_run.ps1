# Runs inside Windows Sandbox: installs winget from the official release files, runs one experiment,
# writes everything to C:\out, then closes the Sandbox.
param([string]$Experiment = "u1", [string]$Arg = "")

$out = "C:\out\$Experiment"
New-Item -ItemType Directory -Force $out | Out-Null
Start-Transcript -Path "$out\setup.log" -Force | Out-Null
try {
    Expand-Archive C:\cache\DesktopAppInstaller_Dependencies.zip C:\deps -Force
    Get-ChildItem C:\deps\x64\*.appx | ForEach-Object { Add-AppxPackage $_.FullName -ErrorAction Continue }
    Add-AppxPackage C:\cache\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle -ErrorAction Continue
    Start-Sleep 5
    $env:Path += ";$env:LOCALAPPDATA\Microsoft\WindowsApps"
    winget --version | Out-File "$out\winget_version.txt" -Encoding utf8
    winget --info | Out-File "$out\winget_info.txt" -Encoding utf8
    (Get-Service DoSvc -ErrorAction SilentlyContinue | Out-String) | Out-File "$out\dosvc.txt" -Encoding utf8

    if ($Experiment -eq "smoke") {
        powershell -ExecutionPolicy Bypass -File C:\spike\smoke.ps1 $out
    } else {
        $env:PYTHONHOME = "C:\py"
        $env:PYTHONPATH = "C:\site"
        $env:PYTHONIOENCODING = "utf-8"
        & C:\py\python.exe "C:\spike\$Experiment.py" $out $Arg *> "$out\run.log"
    }
} catch {
    $_ | Out-File "$out\error.txt"
} finally {
    Stop-Transcript | Out-Null
    "done" | Out-File "$out\DONE.txt"
    shutdown /s /t 5
}
