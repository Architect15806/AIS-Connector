param([Parameter(Mandatory=$true)][ValidatePattern('^[a-p]{32}$')][string]$ExtensionId)
$ErrorActionPreference = 'Stop'
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$hostScript = Join-Path $PSScriptRoot 'native-host\host.py'
$manifestPath = Join-Path $env:LOCALAPPDATA 'AISConnector\native-host\com.ais.connector.json'
& $pythonPath (Join-Path $PSScriptRoot 'native-host\setup.py') $ExtensionId
if ($LASTEXITCODE -ne 0) { throw 'Failed to generate native host registration files.' }
$registryPath = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.ais.connector'
New-Item -Path $registryPath -Force | Out-Null
Set-Item -Path $registryPath -Value $manifestPath
Write-Host 'AIS Connector installed. Reopen the extension side panel.' -ForegroundColor Green
