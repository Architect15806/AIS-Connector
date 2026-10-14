$ErrorActionPreference = 'Stop'
$registryPath = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.ais.connector'
if(Test-Path -LiteralPath $registryPath){Remove-Item -LiteralPath $registryPath}
Write-Host 'Native host unregistered. Existing tunnels and saved credentials are retained. Disconnect tunnels before uninstalling.'
