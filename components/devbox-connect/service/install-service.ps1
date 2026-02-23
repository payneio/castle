# install-service.ps1 - Install devbox-connect as a Windows service using NSSM
#
# Prerequisites:
#   1. Install NSSM: winget install nssm
#   2. Install devbox-connect: uv tool install .
#
# Usage (run as Administrator):
#   .\install-service.ps1 -ConfigPath C:\path\to\tunnels.yaml
#   .\install-service.ps1 -Uninstall
#   .\install-service.ps1 -Status

param(
    [string]$ConfigPath,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$ServiceName = "DevboxConnect"
)

$ErrorActionPreference = "Stop"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-NssmPath {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if ($nssm) {
        return $nssm.Source
    }
    
    # Check common locations
    $paths = @(
        "C:\Program Files\nssm\nssm.exe",
        "C:\Program Files (x86)\nssm\nssm.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\*nssm*\nssm.exe"
    )
    
    foreach ($path in $paths) {
        $found = Get-Item $path -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }
    
    return $null
}

function Get-DevboxConnectPath {
    # Find the uv-installed devbox-connect
    $uvToolPath = "$env:LOCALAPPDATA\uv\tools\devbox-connect"
    if (Test-Path $uvToolPath) {
        # Find the Python executable in the venv
        $pythonPath = Join-Path $uvToolPath "Scripts\python.exe"
        if (Test-Path $pythonPath) {
            return @{
                Python = $pythonPath
                Module = "devbox_connect.cli"
            }
        }
    }
    
    # Try to find via uv tool list
    $uvPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvPath) {
        $toolDir = & uv tool dir 2>$null
        if ($toolDir -and (Test-Path "$toolDir\devbox-connect")) {
            $pythonPath = Join-Path $toolDir "devbox-connect\Scripts\python.exe"
            if (Test-Path $pythonPath) {
                return @{
                    Python = $pythonPath
                    Module = "devbox_connect.cli"
                }
            }
        }
    }
    
    return $null
}

# Check for admin rights
if (-not (Test-Administrator)) {
    Write-Error "This script must be run as Administrator"
    exit 1
}

# Handle status check
if ($Status) {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Service '$ServiceName' status: $($service.Status)"
        Write-Host "Startup type: $($service.StartType)"
    } else {
        Write-Host "Service '$ServiceName' is not installed"
    }
    exit 0
}

# Handle uninstall
if ($Uninstall) {
    $nssm = Get-NssmPath
    if (-not $nssm) {
        Write-Error "NSSM not found. Install with: winget install nssm"
        exit 1
    }
    
    Write-Host "Stopping service..."
    & $nssm stop $ServiceName 2>$null
    
    Write-Host "Removing service..."
    & $nssm remove $ServiceName confirm
    
    Write-Host "Service '$ServiceName' removed"
    exit 0
}

# Install service
if (-not $ConfigPath) {
    Write-Error "ConfigPath is required. Usage: .\install-service.ps1 -ConfigPath C:\path\to\tunnels.yaml"
    exit 1
}

if (-not (Test-Path $ConfigPath)) {
    Write-Error "Config file not found: $ConfigPath"
    exit 1
}

$ConfigPath = (Resolve-Path $ConfigPath).Path

# Find NSSM
$nssm = Get-NssmPath
if (-not $nssm) {
    Write-Error @"
NSSM (Non-Sucking Service Manager) not found.

Install with:
    winget install nssm

Or download from: https://nssm.cc/download
"@
    exit 1
}

# Find devbox-connect
$devboxConnect = Get-DevboxConnectPath
if (-not $devboxConnect) {
    Write-Error @"
devbox-connect not found. Install with:
    uv tool install .

Or from a directory containing the project:
    uv tool install /path/to/devbox-connect
"@
    exit 1
}

Write-Host "Found devbox-connect at: $($devboxConnect.Python)"
Write-Host "Config file: $ConfigPath"
Write-Host ""

# Remove existing service if present
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing service..."
    & $nssm stop $ServiceName 2>$null
    & $nssm remove $ServiceName confirm
}

# Install the service
Write-Host "Installing service '$ServiceName'..."

& $nssm install $ServiceName $devboxConnect.Python "-m" $devboxConnect.Module "-c" $ConfigPath "start"

# Configure service
& $nssm set $ServiceName DisplayName "Devbox Connect SSH Tunnels"
& $nssm set $ServiceName Description "Maintains SSH tunnels to devbox for port forwarding"
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName AppStdout "$env:LOCALAPPDATA\devbox-connect\service.log"
& $nssm set $ServiceName AppStderr "$env:LOCALAPPDATA\devbox-connect\service.log"
& $nssm set $ServiceName AppRotateFiles 1
& $nssm set $ServiceName AppRotateBytes 1048576

# Create log directory
$logDir = "$env:LOCALAPPDATA\devbox-connect"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Write-Host ""
Write-Host "Service '$ServiceName' installed successfully!"
Write-Host ""
Write-Host "Commands:"
Write-Host "  Start:   Start-Service $ServiceName"
Write-Host "  Stop:    Stop-Service $ServiceName"
Write-Host "  Status:  Get-Service $ServiceName"
Write-Host "  Logs:    Get-Content $logDir\service.log -Tail 50"
Write-Host ""
Write-Host "Starting service..."

Start-Service $ServiceName
Get-Service $ServiceName
