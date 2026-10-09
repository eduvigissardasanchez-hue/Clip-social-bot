$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\pythonw.exe'
$main = Join-Path $root 'main.py'
if (!(Test-Path -LiteralPath $python)) { throw 'Ejecuta CONFIGURAR.bat primero.' }
$name = 'ClipsSocialBotBuffer'
$arguments = '"{0}" maintain' -f $main
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing -and (($existing.Actions.Execute -ne $python) -or ($existing.Actions.Arguments -ne $arguments))) {
    throw 'Ya existe una tarea con ese nombre y otra ruta. No se sobrescribira.'
}
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
$daily = New-ScheduledTaskTrigger -Daily -At '03:15'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
# Interactive user token: no stored password. Resumes at login, no persistent console.
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger @($daily, $logon) -Settings $settings -Principal $principal
$task.Description = 'Clips Social Bot: reconciliar Buffer y rellenar la cola local. Requiere sesion del usuario.'
Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
Write-Host 'Tarea instalada: diaria a las 03:15 y al iniciar sesion; recupera ejecuciones perdidas.'
Write-Host 'No necesita una consola abierta. Consulta logs\bot.log. Usa DRY_RUN=false para programar.'
