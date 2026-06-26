# ==============================================================================
# ShakeChecker Development Launcher
# ------------------------------------------------------------------------------
# This script initializes the development environment for ShakeChecker, a
# real‑time Pokémon catch‑probability overlay. It validates Python, activates
# the virtual environment, ensures dependencies are installed, and provides a
# menu for running the app, testing, linting, and building the executable.
#
# This rewritten version removes all QuickEdit toggling and console‑mode
# manipulation. It relies entirely on the terminal's native selection behavior,
# which avoids freezes and allows normal Ctrl+A / Ctrl+C usage.
# ==============================================================================

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# ==============================================================================
# ENVIRONMENT BOOTSTRAP
# ==============================================================================
function Invoke-Bootstrap {
    Write-Host "`n  Checking Python..." -ForegroundColor DarkGray

    try {
        $pyVer = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        $parts = $pyVer -split '\.'
        if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
            Write-Host "`n  Python $pyVer found, but version 3.11+ is required." -ForegroundColor Red
            Pause
            return $false
        }
        Write-Host "  Python $pyVer — OK" -ForegroundColor Green
    }
    catch {
        Write-Host "`n  Python not found in PATH." -ForegroundColor Red
        Pause
        return $false
    }

    if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
        Write-Host "`n  Creating virtual environment..." -ForegroundColor Yellow
        try {
            python -m venv .venv
            Write-Host "  Virtual environment created." -ForegroundColor Green
        }
        catch {
            Write-Host "`n  Failed to create virtual environment." -ForegroundColor Red
            Pause
            return $false
        }
    }

    . ".\.venv\Scripts\Activate.ps1"

    $depsCheck = & python -c "import cv2" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n  Installing dependencies..." -ForegroundColor Yellow
        try {
            pip install -e ".[dev]"
            Write-Host "`n  Dependencies installed." -ForegroundColor Green
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

    return $true
}

$ErrorActionPreference = "Continue"
$ready = Invoke-Bootstrap
$ErrorActionPreference = "Stop"
if (-not $ready) { return }

# ==============================================================================
# HEADER
# ==============================================================================
function Show-Header {
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
    Write-Host "    [Environment: Active]" -ForegroundColor Green
    Write-Host "    ----------------------------------------" -ForegroundColor DarkGray
}

# ==============================================================================
# RUN PYTHON APPLICATION
# ==============================================================================
function Invoke-PythonApp {
    param([string]$ArgsString = "")

    Write-Host "`n  Application running. Press 'q' to terminate.`n" -ForegroundColor DarkGray
    $proc = Start-Process -FilePath "python" -ArgumentList "src\app.py $ArgsString" -PassThru -NoNewWindow

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
    Write-Host "  [1] Start Application" -ForegroundColor White
    Write-Host "  [2] Advanced Run (Custom Arguments)" -ForegroundColor Cyan
    Write-Host "  [3] Embedded Terminal" -ForegroundColor White
    Write-Host "  [4] Ruff (Check --fix & Format)" -ForegroundColor Gray
    Write-Host "  [5] mypy" -ForegroundColor Gray
    Write-Host "  [6] pytest" -ForegroundColor Gray
    Write-Host "  [7] Build Application" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  [Q] Quit" -ForegroundColor DarkRed
    Write-Host "    ----------------------------------------" -ForegroundColor DarkGray
}

# ==============================================================================
# TERMINAL MODE
# ==============================================================================
function Invoke-Terminal {
    $historyFile = Join-Path $PSScriptRoot "logs/launcher_history.log"
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
        Write-Host "    Type 'q' to return | 'cmd' for history" -ForegroundColor DarkGray
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
        $input = Read-Host " "

        # Capture additional pasted lines (if any)
        while ($Host.UI.RawUI.KeyAvailable) {
            $extra = [Console]::In.ReadLine()
            if ($extra -ne $null) {
                $input += "`n$extra"
            }
        }

        if ([string]::IsNullOrWhiteSpace($input)) { continue }
        if ($input -eq 'q') { break }

        if ($input -eq 'cmd') {
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
                $input = $hmap[$sel]
            }
            else { continue }
        }
        elseif ($map.ContainsKey($input)) {
            $input = $map[$input]
        }

        $cmd = $input.Trim()
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

        powershell -NoLogo -NoProfile -Command $cmd
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
            $args = Read-Host "  Enter arguments"
            if ($args) { Invoke-PythonApp -ArgsString $args }
        }
        '3' {
            Invoke-Terminal 
        }
        '4' {
            Clear-Host
            Invoke-Task "Ruff Check" { ruff check --fix . }
            Invoke-Task "Ruff Format" { ruff format . }
            Pause
        }
        '5' {
            Clear-Host
            Invoke-Task "mypy" { mypy . }
            Pause
        }
        '6' {
            Clear-Host
            Invoke-Task "pytest" { pytest }
            Pause
        }
        '7' {
            Clear-Host
            Write-Host "`n  Build Application" -ForegroundColor Cyan
            Write-Host "  ----------------------------------------" -ForegroundColor DarkGray

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
                Write-Host "  Build failed." -ForegroundColor Red
            }
            Pause
        }
        'q' { exit }
        'Q' { exit }
        default {
            Write-Host "  Invalid option." -ForegroundColor Red
            Start-Sleep -Milliseconds 600
        }
    }
}
