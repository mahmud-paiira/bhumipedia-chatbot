#update_live.ps1 - refresh the Bhumipedia datasets on a schedule or on demand (Windows).
#  -Manual    : live progress on the terminal, then a summary of the update.
#  -Cron      : quiet run for Task Scheduler (00:00). Log to logs\update-*.log.
#  -Install   : register a daily 00:00 scheduled task for the current user.
#  -Help      : show this help.
#  -NoRefresh / -Portal / -Docs : passed through to update_datasets.py
#
#  Env: PYTHON=... (default python), LOG_DIR=logs, TASK_NAME='Bhumi dataset update'
#  Exit codes: 0 deployed, 1 rolled back/failed, 2 usage.

[CmdletBinding()]
param(
    [switch]$Manual,
    [switch]$Cron,
    [switch]$Install,
    [switch]$NoRefresh,
    [switch]$Portal,
    [switch]$Docs,
    [switch]$Help
)

Set-Location -LiteralPath $PSScriptRoot

$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
$logDir = if ($env:LOG_DIR) { $env:LOG_DIR } else { (Join-Path $PSScriptRoot 'logs') }
$taskName = if ($env:TASK_NAME) { $env:TASK_NAME } else { 'Bhumi dataset update' }

$extra = @()
if ($NoRefresh) { $extra += '--no-refresh' }
if ($Portal)    { $extra += '--portal' }
if ($Docs)      { $extra += '--docs' }

function Render-Summary {
    $p = Join-Path $PSScriptRoot 'dataset_update.json'
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Output 'no dataset_update.json - nothing has been run yet'
        return
    }
    $s = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
    $line = '=' * 58
    $sym = if ($s.dataset_delta -ge 0) { '+' } else { '' }
    $res = if ($s.ok) { 'OK' } else { 'FAILED' }
    Write-Output $line
    Write-Output ("update report  {0} -> {1}" -f $s.started_at, $s.finished_at)
    Write-Output ("dataset        {0} rows -> {1} rows ({2}{3})" -f $s.dataset_prev, $s.dataset_new, $sym, $s.dataset_delta)
    Write-Output ("result         {0} (exit {1})" -f $res, $s.exit)
    if ($s.stages) {
        foreach ($st in $s.stages) {
            Write-Output ("  {0,-38} {1,6:f1}s" -f $st.step, $st.duration_s)
        }
    }
    if ($s.tests) {
        foreach ($name in $s.tests.PSObject.Properties.Name) {
            $t = $s.tests.$name
            $mark = if ($t.ok) { 'PASS' } else { 'FAIL' }
            Write-Output ("  {0,-38} {1}" -f $name, $mark)
        }
    }
    if ($s.warnings) { foreach ($w in $s.warnings) { Write-Output ("  WARN  {0}" -f $w) } }
    if ($s.error)    { Write-Output ("  ERROR {0}" -f $s.error) }
    Write-Output $line
}

if ($Help) {
    Get-Content -LiteralPath $PSCommandPath | Where-Object { $_ -match '^#' } | ForEach-Object { $_.Substring(1) }
    exit 0
}

if ($Install) {
    $exe = 'powershell.exe'
    $argsLine = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Cron"
    $action = New-ScheduledTaskAction -Execute $exe -Argument $argsLine -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 0 -Minute 0 -Second 0)
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "replaced existing task: $taskName"
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Description 'Refresh Bhumipedia chatbot datasets from the live API' -Force | Out-Null
    Write-Output "installed scheduled task '$taskName' running daily at 00:00"
    Write-Output "run it now with:  schtasks /run /tn `"$taskName`""
    exit 0
}

$oldOutputEncoding = $null
try {
    $oldOutputEncoding = [Console]::OutputEncoding
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $env:PYTHONIOENCODING = 'utf-8'

    if ($Cron -or -not [Environment]::UserInteractive) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $out = Join-Path $logDir ("update-{0}.log" -f $stamp)
        & $python update_datasets.py --quiet @extra 2>&1 | Tee-Object -FilePath $out
        $rc = $LASTEXITCODE
        Render-Summary | Add-Content -LiteralPath $out -Encoding UTF8
        Add-Content -LiteralPath (Join-Path $logDir 'cron.log') -Encoding UTF8 -Value `
            ("[{0}] update_live rc={1} log={2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $rc, $out)
        Write-Output "run finished: rc=$rc  full log: $out"
        exit $rc
    }

    & $python update_datasets.py @extra
    $rc = $LASTEXITCODE
    Write-Output ''
    Render-Summary
    exit $rc
}
finally {
    if ($null -ne $oldOutputEncoding) {
        [Console]::OutputEncoding = $oldOutputEncoding
    }
}