# ==============================================================================
# ShakeChecker Development Launcher
# ------------------------------------------------------------------------------
# This script initializes the development environment for ShakeChecker.
# It validates Python, activates the virtual environment, installs dependencies, 
# and provides a menu for running the app, testing, linting, and building.
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PWD.Path
$env:PYTHONPYCACHEPREFIX = Join-Path $PWD.Path ".pycache"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ==============================================================================
# HEADER
# ==============================================================================
function Show-Header {
    param([switch]$IsInstaller)
    Clear-Host
    Write-Host ""
    Write-Host "    ███████╗██╗  ██╗ █████╗ ██╗  ██╗███████╗ " -ForegroundColor Red
    Write-Host "    ██╔════╝██║  ██║██╔══██╗██║ ██╔╝██╔════╝ " -ForegroundColor Red
    Write-Host "    ███████╗███████║███████║█████═╝ █████╗   " -ForegroundColor Red
    Write-Host "    ╚════██║██╔══██║██╔══██║██╔═██╗ ██╔══╝   " -ForegroundColor DarkGray
    Write-Host "    ███████║██║  ██║██║  ██║██║  ██╗███████╗ " -ForegroundColor White
    Write-Host "    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ " -ForegroundColor White
    Write-Host "          C H E C K E R   V 1 . 2 . 0        " -ForegroundColor DarkGray
    Write-Host ""
    if ($IsInstaller) {
        Write-Host "    [System Initialization & Installer]" -ForegroundColor Cyan
    }
    else {
        Write-Host "    [Environment: Active]" -ForegroundColor Green
    }
    Write-Host "    ----------------------------------------" -ForegroundColor DarkGray
}

# ==============================================================================
# ENVIRONMENT BOOTSTRAP
# ------------------------------------------------------------------------------
# Core initialization routine. Handles:
# 1. Validating Python 3.11+ is installed in PATH
# 2. Creating the .venv virtual environment if it doesn't exist
# 3. Checking if dependencies are already satisfied via test import
# 4. Bootstrapping 'uv' (Rust-based ultra-fast package installer)
# 5. Executing concurrent high-speed dependency installations with visual spinners
# ==============================================================================
function Invoke-Bootstrap {
    Show-Header -IsInstaller
    $isFreshInstall = $false
    
    # --------------------------------------------------------------------------
    # Python Version Validation
    # --------------------------------------------------------------------------
    Write-Host "`n  Checking Python..." -ForegroundColor DarkGray

    $pyCmd = "python"
    $venvArgs = "-m venv .venv"
    $pyFound = $true

    try {
        $pyVer = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Not found" }
    }
    catch {
        $pyCmd = "py"
        $venvArgs = "-3 -m venv .venv"
        try {
            $pyVer = & $pyCmd -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
            if ($LASTEXITCODE -ne 0) { throw "Not found" }
        }
        catch {
            $pyFound = $false
        }
    }

    if (-not $pyFound) {
        Write-Host "`n  Python not found on system. Please install Python 3.11+." -ForegroundColor Red
        Pause
        return $false
    }

    if ([version]$pyVer -lt [version]"3.11") {
        Write-Host "`n  Python $pyVer found, but version 3.11+ is required." -ForegroundColor Red
        Pause
        return $false
    }
    Write-Host "  Python $pyVer — OK" -ForegroundColor Green

    # --------------------------------------------------------------------------
    # Virtual Environment Setup
    # --------------------------------------------------------------------------
    if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
        Write-Host "`n  No virtual environment found. A clean installation is required." -ForegroundColor Cyan
        $confirm = Read-Host "  Do you want to create a virtual environment now? (Y/N)"
        if ($confirm -notmatch '^[Yy]') {
            Write-Host "`n  Installation aborted." -ForegroundColor Red
            Pause
            return $false
        }
        Write-Host ""
        try {
            $procVenv = Start-Process -FilePath $pyCmd -ArgumentList $venvArgs -WindowStyle Hidden -PassThru
            $spinners = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
            $i = 0
            try { [Console]::CursorVisible = $false } catch {}
            
            while (-not $procVenv.HasExited) {
                Write-Host "`r  $($spinners[$i]) Creating virtual environment..." -NoNewline -ForegroundColor Yellow
                $i = ($i + 1) % $spinners.Length
                Start-Sleep -Milliseconds 80
            }
            if ($procVenv.ExitCode -ne 0) { throw "venv failed" }
            Write-Host "`r  Virtual environment created.                    " -ForegroundColor Green
            
            $procPip = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m pip install --upgrade pip -q" -WindowStyle Hidden -PassThru
            while (-not $procPip.HasExited) {
                Write-Host "`r  $($spinners[$i]) Upgrading pip...                 " -NoNewline -ForegroundColor DarkGray
                $i = ($i + 1) % $spinners.Length
                Start-Sleep -Milliseconds 80
            }
            Write-Host "`r                                                    `r" -NoNewline
            try { [Console]::CursorVisible = $true } catch {}
            $isFreshInstall = $true
        }
        catch {
            Write-Host "`n  Failed to create virtual environment." -ForegroundColor Red
            Pause
            return $false
        }
    }

    . ".\.venv\Scripts\Activate.ps1"

    # --------------------------------------------------------------------------
    # Dependency Check & Installation
    # --------------------------------------------------------------------------
    # Attempt a fast check by trying to import a core dependency (cv2)
    $null = & python -c "import cv2" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n  Missing dependencies detected." -ForegroundColor Cyan

        $confirm = Read-Host "  Do you want to install them now? (~600 MB) (Y/N)"
        if ($confirm -notmatch '^[Yy]') {
            Write-Host "`n  Installation aborted." -ForegroundColor Red
            Pause
            return $false
        }
        Write-Host ""
        
        try {
            # ------------------------------------------------------------------
            # UV Accelerated Installation
            # ------------------------------------------------------------------
            # Standard pip is single-threaded and notoriously slow when resolving
            # and downloading large binaries (like PyQt6 and OpenCV). We bootstrap 
            # `uv` (a blazingly fast Rust-based package installer) via standard pip, 
            # and then use `uv` to install the actual dependencies concurrently.
            # ------------------------------------------------------------------
            $spinners = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
            $i = 0
            try { [Console]::CursorVisible = $false } catch {}

            $uvLog = Join-Path $env:TEMP "uv_bootstrap_$([guid]::NewGuid()).log"
            $uvErr = Join-Path $env:TEMP "uv_bootstrap_err_$([guid]::NewGuid()).log"
            $procUv = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m pip install uv -q" -WindowStyle Hidden -RedirectStandardOutput $uvLog -RedirectStandardError $uvErr -PassThru
            while (-not $procUv.HasExited) {
                Write-Host "`r  $($spinners[$i]) Preparing installation...                  " -NoNewline -ForegroundColor DarkGray
                $i = ($i + 1) % $spinners.Length
                Start-Sleep -Milliseconds 80
            }
            Start-Sleep -Milliseconds 300
            
            if ($procUv.ExitCode -ne 0) {
                Write-Host "`n  Dependency installation failed (uv bootstrap error)." -ForegroundColor Red
                Get-Content $uvLog -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkGray
                Get-Content $uvErr -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkRed
                Pause
                return $false
            }
            
            $installLog = Join-Path $env:TEMP "pip_install_$([guid]::NewGuid()).log"
            $installErr = Join-Path $env:TEMP "pip_install_err_$([guid]::NewGuid()).log"
            $procInstall = Start-Process -FilePath ".\.venv\Scripts\uv.exe" -ArgumentList "pip install --python .\.venv -e `".[dev,build]`"" -WindowStyle Hidden -RedirectStandardOutput $installLog -RedirectStandardError $installErr -PassThru
            
            while (-not $procInstall.HasExited) {
                Write-Host "`r  $($spinners[$i]) Installing dependencies...    " -NoNewline -ForegroundColor Yellow
                $i = ($i + 1) % $spinners.Length
                Start-Sleep -Milliseconds 80
            }
            Start-Sleep -Milliseconds 300
            Write-Host "`r                                                                      `r" -NoNewline
            try { [Console]::CursorVisible = $true } catch {}
            
            if ($procInstall.ExitCode -eq 0) {
                Write-Host "  Dependencies installed. [100%]" -ForegroundColor Green
                $isFreshInstall = $true
            }
            else {
                Write-Host "  Dependency installation failed." -ForegroundColor Red
                Get-Content $installLog -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkGray
                Get-Content $installErr -ErrorAction SilentlyContinue | Write-Host -ForegroundColor DarkRed
                Pause
                return $false
            }
            Remove-Item $uvLog -Force -ErrorAction SilentlyContinue
            Remove-Item $uvErr -Force -ErrorAction SilentlyContinue
            Remove-Item $installLog -Force -ErrorAction SilentlyContinue
            Remove-Item $installErr -Force -ErrorAction SilentlyContinue
        }
        catch {
            Write-Host "`n  Dependency installation failed." -ForegroundColor Red
            Pause
            return $false
        }
    }
    else {
        Write-Host "  Dependencies — OK" -ForegroundColor Green
    }

    # --------------------------------------------------------------------------
    # Desktop Shortcut Prompter
    # --------------------------------------------------------------------------
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop "ShakeChecker.lnk"
    if ($isFreshInstall -and -not (Test-Path $shortcutPath)) {
        Write-Host ""
        $confirm = Read-Host "  Do you want to create a Desktop shortcut? (Y/N)"
        if ($confirm -match '^[Yy]') {
            try {
                $wshell = New-Object -ComObject WScript.Shell
                $shortcut = $wshell.CreateShortcut($shortcutPath)
                $shortcut.TargetPath = Join-Path $PWD.Path "run_launcher.cmd"
                $shortcut.WorkingDirectory = $PWD.Path
                
                $iconPath = Join-Path $PWD.Path "data\shakechecker.ico"
                if (-not (Test-Path $iconPath)) { $iconPath = Join-Path $PWD.Path "assets\shakechecker.ico" }
                if (-not (Test-Path $iconPath)) { $iconPath = Join-Path $PWD.Path "shakechecker.ico" }
                
                if (Test-Path $iconPath) {
                    $shortcut.IconLocation = $iconPath
                }
                $shortcut.Save()
                Write-Host "  Shortcut created successfully!" -ForegroundColor Green
                Start-Sleep -Milliseconds 600
            }
            catch {
                Write-Host "  [Debug] Failed to create shortcut: $($_.Exception.Message)" -ForegroundColor DarkGray
            }
        }
    }

    return $true
}

$ErrorActionPreference = "Continue"
$ready = Invoke-Bootstrap
$ErrorActionPreference = "Stop"
if (-not $ready) { return }

# ==============================================================================
# RUN PYTHON APPLICATION
# ==============================================================================
function Invoke-PythonApp {
    param([string]$ArgsString = "")

    Write-Host "`n  Application running. Press 'q' to terminate.`n" -ForegroundColor DarkGray
    $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "src\app.py $ArgsString" -PassThru -NoNewWindow

    while (-not $proc.HasExited) {
        $key = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        if ($key.Character -eq 'q' -or $key.Character -eq 'Q') {
            Write-Host "`n  Terminating..." -ForegroundColor Yellow
            $proc.Kill()
            break
        }
    }

    Write-Host "`n  Application closed." -ForegroundColor DarkGray
    Pause
}

# ==============================================================================
# GENERIC TASK RUNNER
# ==============================================================================
function Invoke-Task {
    param(
        [string]$Title,
        [scriptblock]$Command
    )

    Write-Host "`n  [>] $Title" -ForegroundColor Magenta
    Write-Host "    $($Command.ToString().Trim())`n" -ForegroundColor DarkGray

    try {
        & $Command
    }
    catch {
        Write-Host "  Task failed." -ForegroundColor Red
    }
}

# ==============================================================================
# MENU
# ==============================================================================
function Show-Menu {
    Show-Header
    Write-Host "  --- Application ---" -ForegroundColor Yellow
    Write-Host "  [1] Start Application" -ForegroundColor White
    Write-Host "  [2] Advanced Run (Custom Arguments)" -ForegroundColor Cyan
    Write-Host "  [3] Build Executable (.exe)" -ForegroundColor White
    Write-Host ""
    Write-Host "  --- Development & Tools ---" -ForegroundColor Yellow
    Write-Host "  [4] Embedded Terminal" -ForegroundColor Gray
    Write-Host "  [5] Ruff (Check --fix & Format)" -ForegroundColor Gray
    Write-Host "  [6] Type Checking (mypy)" -ForegroundColor Gray
    Write-Host "  [7] Unit Tests (pytest)" -ForegroundColor Gray
    Write-Host "  [8] Clean Environment" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  [Q] Quit" -ForegroundColor DarkRed
    Write-Host "    ----------------------------------------" -ForegroundColor DarkGray
}

# ==============================================================================
# TERMINAL MODE
# ------------------------------------------------------------------------------
# Simulates a persistent REPL terminal for the virtual environment. 
# It reads historical commands from a log file, allows users to execute standard
# PowerShell commands or git tools, captures multi-line pasted text via KeyAvailable, 
# and safely evaluates them via Invoke-Expression without dropping the UI.
# ==============================================================================
function Invoke-Terminal {
    $historyFile = Join-Path $PWD.Path "logs/launcher_history.log"
    $cmdHistory = @{}
    $seq = 0

    if (Test-Path $historyFile) {
        foreach ($line in Get-Content $historyFile) {
            if ($line -match '^(.+)\|(\d+)\|(\d+)$') {
                $cmdHistory[$matches[1]] = @{ Count = [int]$matches[2]; Seq = [int]$matches[3] }
                if ([int]$matches[3] -gt $seq) { $seq = [int]$matches[3] }
            }
        }
    }

    while ($true) {
        Clear-Host
        Write-Host "    [ TERMINAL MODE ]" -ForegroundColor Cyan
        Write-Host "    Type 'q' to return | 'h' for history" -ForegroundColor DarkGray
        Write-Host "    ----------------------------------------" -ForegroundColor DarkGray

        $top = $cmdHistory.GetEnumerator() | Sort-Object { $_.Value.Count } -Descending | Select-Object -First 5
        $map = @{}
        $i = 1
        foreach ($c in $top) {
            $lines = $c.Name.Split("`n")
            $firstLine = $lines[0]
            $indicator = if ($lines.Count -gt 1) { "(Multi-line)" } else { "" }
            Write-Host "      [$i] $firstLine$indicator" -ForegroundColor Gray
            $map["$i"] = $c.Name
            $i++
        }

        Write-Host "  ❯ " -NoNewline -ForegroundColor Gray
        Write-Host "(.venv)" -NoNewline -ForegroundColor Green

        # Read first line
        $userInput = Read-Host " "

        # Capture additional pasted lines (if any)
        while ($Host.UI.RawUI.KeyAvailable) {
            $extra = [Console]::In.ReadLine()
            if ($null -ne $extra) {
                $userInput += "`n$extra"
            }
        }

        if ([string]::IsNullOrWhiteSpace($userInput)) { continue }
        if ($userInput -eq 'q') { break }

        if ($userInput -eq 'h') {
            Write-Host "`n  Command History" -ForegroundColor Cyan
            $all = $cmdHistory.GetEnumerator() | Sort-Object { $_.Value.Count } -Descending
            $hmap = @{}
            $j = 1
            foreach ($c in $all) {
                $lines = $c.Name.Split("`n")
                $firstLine = $lines[0]
                $indicator = if ($lines.Count -gt 1) { " ↵" } else { "" }
                Write-Host "    [$j] $firstLine$indicator (used $($c.Value.Count) times)" -ForegroundColor Gray
                $hmap["$j"] = $c.Name
                $j++
            }
            $sel = Read-Host "  Select number"
            if ($hmap.ContainsKey($sel)) {
                $userInput = $hmap[$sel]
            }
            else { continue }
        }
        elseif ($map.ContainsKey($userInput)) {
            $userInput = $map[$userInput]
        }

        $cmd = $userInput.Trim()
        $seq++
        if (-not $cmdHistory.ContainsKey($cmd)) {
            $cmdHistory[$cmd] = @{ Count = 0; Seq = $seq }
        }
        $cmdHistory[$cmd].Count++
        $cmdHistory[$cmd].Seq = $seq

        if ($cmdHistory.Count -gt 100) {
            $old = $cmdHistory.GetEnumerator() | Sort-Object { $_.Value.Seq } | Select-Object -First ($cmdHistory.Count - 100)
            foreach ($e in $old) { $cmdHistory.Remove($e.Name) }
        }

        $cmdHistory.GetEnumerator() |
        ForEach-Object { "$($_.Name)|$($_.Value.Count)|$($_.Value.Seq)" } |
        Set-Content $historyFile

        try { Invoke-Expression $cmd } catch { Write-Host $_ -ForegroundColor Red }
        Write-Host "`n  (press Enter to continue)" -ForegroundColor DarkGray
        [void][System.Console]::ReadLine()
    }
}

# ==============================================================================
# MAIN LOOP
# ==============================================================================
while ($true) {
    Show-Menu
    $choice = Read-Host "  Select an option"

    switch ($choice) {
        '1' { Invoke-PythonApp }
        '2' {
            Clear-Host
            Write-Host "`n  Advanced Run Mode" -ForegroundColor Cyan
            Write-Host "  ----------------------------------------" -ForegroundColor DarkGray
            Write-Host "  --species <Name>"
            Write-Host "  --status <Status>"
            Write-Host "  --rate <Number>"
            Write-Host "  --image <Path>"
            Write-Host "  --list-windows"
            Write-Host ""
            $userArgs = Read-Host "  Enter arguments"
            if ($userArgs) { Invoke-PythonApp -ArgsString $userArgs }
        }
        '3' {
            Clear-Host
            Write-Host "`n  Build Application" -ForegroundColor Cyan
            Write-Host "  ----------------------------------------" -ForegroundColor DarkGray

            # ------------------------------------------------------------------
            # Differential Build Check
            # ------------------------------------------------------------------
            # Check if any core source files have been modified more recently 
            # than the final .exe file to avoid unnecessary PyInstaller rebuilds.
            $exe = "dist\ShakeChecker\ShakeChecker.exe"
            $needs = $true

            if (Test-Path $exe) {
                $exeTime = (Get-Item $exe).LastWriteTime
                $paths = @("src", "assets", "calibration.toml", "pyproject.toml", "ShakeChecker.spec")

                foreach ($p in $paths) {
                    if (Test-Path $p) {
                        $changed = Get-ChildItem $p -Recurse -File |
                        Where-Object { $_.LastWriteTime -gt $exeTime -and $_.Extension -ne '.pyc' -and $_.FullName -notmatch '__pycache__' }
                        if ($changed) {
                            $needs = $true
                            break
                        }
                        else { $needs = $false }
                    }
                }
            }

            if (-not $needs) {
                Write-Host "  No changes detected. Build is up to date." -ForegroundColor Green
                Write-Host "  Output: dist/ShakeChecker/" -ForegroundColor Yellow
                Pause
                continue
            }

            Write-Host "`n  Running PyInstaller..." -ForegroundColor Magenta
            try {
                if (Test-Path ".\.venv\Scripts\pyinstaller.exe") {
                    & ".\.venv\Scripts\pyinstaller.exe" --noconfirm ShakeChecker.spec
                }
                else {
                    pyinstaller --noconfirm ShakeChecker.spec
                }
                Write-Host "`n  Build complete!" -ForegroundColor Green
                Write-Host "  Output: dist/ShakeChecker/" -ForegroundColor Yellow
            }
            catch {
                Write-Host "  Build failed: $_" -ForegroundColor Red
            }
            Pause
        }
        '4' {
            Invoke-Terminal 
        }
        '5' {
            Clear-Host
            Invoke-Task "Ruff Check" { ruff check --fix . }
            Invoke-Task "Ruff Format" { ruff format . }
            Pause
        }
        '6' {
            Clear-Host
            Invoke-Task "mypy" { mypy . }
            Pause
        }
        '7' {
            Clear-Host
            Invoke-Task "pytest" { pytest }
            Pause
        }
        '8' {
            Clear-Host
            Write-Host "`n  Cleaning environment..." -ForegroundColor Cyan
            $targets = @("build", "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".pycache")
            
            if (Test-Path ".venv") {
                $delVenv = Read-Host "  Do you want to completely remove the virtual environment? (Y/N)"
                if ($delVenv -match '^[Yy]') {
                    $targets = @(".venv") + $targets
                }
            }

            $oldProg = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            foreach ($t in $targets) {
                if (Test-Path $t) {
                    Write-Host "  Removing $t..." -ForegroundColor Gray
                    Remove-Item -Recurse -Force $t
                }
            }
            $ProgressPreference = $oldProg
            Write-Host "  Done.`n" -ForegroundColor Green
            Write-Host "  Rebooting environment..." -ForegroundColor Cyan
            Start-Sleep -Milliseconds 600
            Clear-Host
            
            $ready = Invoke-Bootstrap
            if (-not $ready) {
                Write-Host "`n  Bootstrap aborted. Exiting launcher." -ForegroundColor Red
                Pause
                exit
            }
        }
        'q' { exit }
        'Q' { exit }
        default {
            Write-Host "  Invalid option." -ForegroundColor Red
            Start-Sleep -Milliseconds 600
        }
    }
}
