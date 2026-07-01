# Creates a Windows desktop shortcut for Interferometer Automation.
# Points the shortcut at .venv\Scripts\pythonw.exe with main.py as the argument
# so double-click launches the app without opening a console window.
# Requires a venv at the project root (see README setup).

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$MainPy = Join-Path $ProjectRoot "main.py"
$Icon = Join-Path $ProjectRoot "assets\icons\app_icon.ico"
$VenvPythonw = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPythonw)) {
    Write-Error "Virtual env not found. Run: python -m venv .venv && pip install -r requirements.txt"
    exit 1
}

$Desktop = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path $Desktop)) {
    New-Item -ItemType Directory -Force -Path $Desktop | Out-Null
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut((Join-Path $Desktop "Interferometer Automation.lnk"))
$Shortcut.TargetPath = $VenvPythonw
$Shortcut.Arguments = "`"$MainPy`""
$Shortcut.WorkingDirectory = $ProjectRoot
if (Test-Path $Icon) {
    $Shortcut.IconLocation = "$Icon,0"
} else {
    $PngIcon = Join-Path $ProjectRoot "assets\icons\app_icon.png"
    if (Test-Path $PngIcon) { $Shortcut.IconLocation = "$PngIcon,0" }
}
$Shortcut.Description = "Interferometer Automation"
$Shortcut.Save()
Write-Host "Desktop shortcut created: Interferometer Automation.lnk"
Write-Host "Launcher: $VenvPythonw `"$MainPy`""
