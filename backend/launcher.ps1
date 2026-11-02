$Root = $PSScriptRoot
$ErrorActionPreference = 'Stop'
Set-Location $Root
$state = Join-Path $Root '.drone-fire-server.pid'
$log = Join-Path $Root 'launcher.log'
$port = 8000
function Get-ServerProcess($id) {
  if (!$id -or $id -le 0) { return $null }
  $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if (!$procInfo -or !$procInfo.CommandLine) { return $null }
  $cmd = $procInfo.CommandLine.Replace('\','/').ToLowerInvariant()
  $serverPath = (Join-Path $Root 'server.py').Replace('\','/').ToLowerInvariant()
  if ($cmd.Contains($serverPath)) { return $procInfo }
  return $null
}
function Stop-OurServer($id) {
  $target = Get-ServerProcess $id
  if (!$target) { return $false }
  # أوقف عملية الخادم المستمعة وأي عمليات فرعية تابعة لهذا الخادم فقط.
  $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue)
  foreach ($child in $children) { Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue }
  Stop-Process -Id $id -Force -ErrorAction Stop
  for ($n=0; $n -lt 30; $n++) {
    Start-Sleep -Milliseconds 200
    if (!(Get-Process -Id $id -ErrorAction SilentlyContinue)) { break }
  }
  return $true
}
try {
  $saved = 0
  if (Test-Path $state) { [void][int]::TryParse((Get-Content $state -Raw).Trim(), [ref]$saved) }
  $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  $liveId = if ($listener) { [int]$listener.OwningProcess } else { 0 }
  $targetId = 0
  if (Get-ServerProcess $saved) { $targetId = $saved }
  elseif (Get-ServerProcess $liveId) { $targetId = $liveId }
  if ($targetId -gt 0) {
    [void](Stop-OurServer $targetId)
    Remove-Item $state -Force -ErrorAction SilentlyContinue
    Write-Host 'Project stopped. You can start it again now.'
    exit 0
  }
  if (Test-Path $state) { Remove-Item $state -Force }
  if ($listener) { throw "Port $port belongs to another application (PID $liveId). No process was terminated." }
  $python = Join-Path $Root '.venv\Scripts\python.exe'
  if (!(Test-Path $python)) {
    $candidates = @('py','python','python3')
    $found = $false
    foreach ($candidate in $candidates) {
      if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $arguments = if ($candidate -eq 'py') { @('-3','-m','venv', (Join-Path $Root '.venv')) } else { @('-m','venv',(Join-Path $Root '.venv')) }
        & $candidate @arguments
        if ($LASTEXITCODE -eq 0 -and (Test-Path $python)) { $found=$true; break }
      }
    }
    if (!$found) { throw 'Python 3 not found. Install Python 3 with Add Python to PATH enabled.' }
  }
  $marker = Join-Path $Root '.venv\.requirements-ready'
  if (!(Test-Path $marker)) {
    Write-Host 'Installing dependencies (first launch may take several minutes)...'
    & $python -m pip install -r (Join-Path $Root 'requirements.txt') --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet connection.' }
    Set-Content $marker 'installed'
  }
  $server = Join-Path $Root 'server.py'
  $stdout = Join-Path $Root 'server-output.log'
  $stderr = Join-Path $Root 'server-error.log'
  $proc = Start-Process -FilePath $python -ArgumentList ('"' + $server + '"') -WorkingDirectory $Root -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $ok = $false
  for ($i=0; $i -lt 35; $i++) {
    Start-Sleep -Seconds 1
    $proc.Refresh()
    if ($proc.HasExited) { break }
    try {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:$port/" -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -eq 200) { $ok=$true; break }
    } catch {}
  }
  if (!$ok) {
    if (!$proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    throw "Server did not become ready. Inspect server-error.log and server-output.log."
  }
  $actualListener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  $trackedId = if ($actualListener -and (Get-ServerProcess ([int]$actualListener.OwningProcess))) { [int]$actualListener.OwningProcess } else { $proc.Id }
  Set-Content $state $trackedId
  Start-Process "http://127.0.0.1:$port/?v=navload-20261012a"
  Write-Host "Project running at http://127.0.0.1:$port/ (PID $($proc.Id))."
  exit 0
} catch {
  $message = $_.Exception.Message
  Add-Content $log "$(Get-Date -Format o) $message"
  Write-Host "ERROR: $message" -ForegroundColor Red
  exit 1
}
