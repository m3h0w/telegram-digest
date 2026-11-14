# Telegram Digest - installer / updater for Windows. Paste into PowerShell:
#
#   irm https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.ps1 | iex
#
# Installs into your user folder\TelegramDigest, keeps your settings and saved messages when
# updating, starts the app in the background (and at every login) and opens http://localhost:8765.
# No administrator rights needed.

& {
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # downloads are much faster without the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$ZipUrl = 'https://github.com/m3h0w/telegram-digest/archive/refs/heads/main.zip'
$Dest   = Join-Path $HOME 'TelegramDigest'
$Files  = @('app.py', 'export.py', 'ui.html', 'service.pyw', 'install.ps1', 'README.md', 'AI-SETUP.md', 'HOW-TO-DIGEST.md', '.env.example')
$Port   = 8765

function Say($text) { Write-Host "-> $text" -ForegroundColor Cyan }
function Stop-WithMessage($text) { Write-Host ""; Write-Host $text -ForegroundColor Yellow; Write-Host ""; throw "Setup stopped." }

function Test-Python($exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }    # the Microsoft Store shortcut, not real Python
    try { & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}

function Find-Python {
    $candidates = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try { $candidates += (& $py.Source -3 -c "import sys; print(sys.executable)" 2>$null) } catch { }
    }
    $p = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($p) { $candidates += $p.Source }
    foreach ($v in '313', '312', '311', '310', '314') {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe")
        $candidates += (Join-Path $env:ProgramFiles "Python$v\python.exe")
    }
    foreach ($c in $candidates) { if ($c -and (Test-Python ([string]$c).Trim())) { return ([string]$c).Trim() } }
    return $null
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

try {
    Write-Host ""
    Write-Host "Telegram Digest setup" -ForegroundColor Green

    # 1. Python (Windows doesn't come with it)
    Say "Looking for Python..."
    $Python = Find-Python
    if (-not $Python) {
        if (Get-Command winget.exe -ErrorAction SilentlyContinue) {
            Say "Installing Python (a few minutes; Windows may ask you to allow it)..."
            & winget.exe install --exact --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
            Refresh-Path
            $Python = Find-Python
        }
        if (-not $Python) {
            Stop-WithMessage ("Python is needed but couldn't be installed automatically.`n" +
                "1. Open https://www.python.org/downloads/ and click the yellow Download button.`n" +
                "2. Run the installer and tick 'Add python.exe to PATH' at the bottom of the first screen.`n" +
                "3. Close this window, open PowerShell again and paste the same line.")
        }
    }
    Say "Using Python at $Python"

    # 2. Download the app
    Say "Downloading Telegram Digest..."
    $Tmp = Join-Path ([IO.Path]::GetTempPath()) ("tgd-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    $Zip = Join-Path $Tmp 'app.zip'
    Invoke-WebRequest -UseBasicParsing -Uri $ZipUrl -OutFile $Zip
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $Src = Get-ChildItem -Path $Tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    foreach ($f in $Files) {
        $from = Join-Path $Src.FullName $f
        if (Test-Path $from) { Copy-Item -Path $from -Destination (Join-Path $Dest $f) -Force }
    }
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
    Say "Installed to $Dest"

    # 3. Stop a copy that is already running, so the new files are used
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Dest*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1

    # 4. Its own Python environment with the two packages it needs
    Say "Setting up (a minute or two the first time)..."
    $Venv = Join-Path $Dest '.venv'
    $VPython = Join-Path $Venv 'Scripts\python.exe'
    $VPythonW = Join-Path $Venv 'Scripts\pythonw.exe'
    if (-not (Test-Path $VPython)) {
        & $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { Stop-WithMessage "Couldn't create the Python environment in $Venv." }
    }
    & $VPython -m pip install --quiet --disable-pip-version-check --upgrade pip telethon certifi
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "Couldn't install the packages it needs. Check the internet connection and paste the line again." }

    # 5. Start at login, without a window: a shortcut in the Startup folder
    Say "Starting it in the background (it also starts when you log in)..."
    $Startup = [Environment]::GetFolderPath('Startup')
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut((Join-Path $Startup 'Telegram Digest.lnk'))
    $Link.TargetPath = $VPythonW
    $Link.Arguments = '"' + (Join-Path $Dest 'service.pyw') + '"'
    $Link.WorkingDirectory = $Dest
    $Link.Description = 'Keeps Telegram Digest running in the background'
    $Link.WindowStyle = 7
    $Link.Save()
    Start-Process -FilePath $VPythonW -ArgumentList ('"' + (Join-Path $Dest 'service.pyw') + '"') -WorkingDirectory $Dest -WindowStyle Hidden

    # 6. Wait for it, then open the page
    $up = $false
    for ($i = 0; $i -lt 40; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 2 | Out-Null; $up = $true; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $up) {
        Stop-WithMessage "It installed but didn't start. The log is in $Dest\logs\app.log. Paste the same line again to retry."
    }
    Write-Host ""
    Write-Host "Running at http://localhost:$Port" -ForegroundColor Green
    Start-Process "http://localhost:$Port"
    Write-Host "Next: follow the guided setup in the page that just opened. Bookmark http://localhost:$Port"
    Write-Host ""
}
catch {
    if ($_.Exception.Message -ne 'Setup stopped.') {
        Write-Host ""
        Write-Host ("Something went wrong: " + $_.Exception.Message) -ForegroundColor Red
        Write-Host "Paste the same line again to retry. If it keeps failing, show this message to your AI assistant."
    }
}
}
