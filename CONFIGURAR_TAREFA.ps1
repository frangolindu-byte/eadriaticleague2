$taskName = "eAdriaticLeague_Robo"
$scriptDir = "C:\Users\Edson\eadriaticleague2"
$vbsPath = "$scriptDir\EXECUTAR_ROBO_SILENCIOSO.vbs"

# Remove tarefa existente se houver
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Cria a tarefa que roda a cada 30 minutos
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`"" -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration ([TimeSpan]::FromDays(365))
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::FromHours(2))

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Robo eAdriatic League - roda silenciosamente a cada 30 minutos"

Write-Host "Tarefa '$taskName' criada com sucesso!"
Write-Host "Intervalo: a cada 30 minutos"
Write-Host "Para alterar o intervalo, edite a tarefa no Agendador de Tarefas."
