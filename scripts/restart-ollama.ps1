# Restart Ollama cleanly for Poiesis.
#
# Why this exists: killing ollama.exe leaves its llama-server.exe model runners
# alive. Each one keeps its share of GPU memory, so the next load gets less of the
# GPU and more of the model runs on the CPU. Three such orphans once cut prompt
# speed from ~1,200 to ~60 tokens per second, and finally stopped the model from
# loading at all ("llama-server startup failed after projector CPU offload").
#
# It also starts the server without OLLAMA_KV_CACHE_TYPE and
# OLLAMA_FLASH_ATTENTION, which slow the qwen3.6 35B-A3B hybrid model on this
# machine, and binds to all interfaces so the containers can reach it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\restart-ollama.ps1

$ErrorActionPreference = "Stop"

Get-Process | Where-Object { $_.ProcessName -match '^(ollama|ollama app|llama-server)$' } | Stop-Process -Force
Start-Sleep -Seconds 4
$left = @(Get-Process | Where-Object { $_.ProcessName -match 'llama-server|ollama' })
if ($left.Count) { throw "still running: $($left.ProcessName -join ', ')" }

$exe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $exe
$psi.Arguments = "serve"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
[void]$psi.EnvironmentVariables.Remove("OLLAMA_KV_CACHE_TYPE")
[void]$psi.EnvironmentVariables.Remove("OLLAMA_FLASH_ATTENTION")
$psi.EnvironmentVariables["OLLAMA_HOST"] = "0.0.0.0:11434"
$psi.EnvironmentVariables["OLLAMA_KEEP_ALIVE"] = "30m"
$psi.EnvironmentVariables["OLLAMA_MAX_LOADED_MODELS"] = "1"
# Leave 1.5 GB of VRAM to the display driver. With the GPU filled to the brim the
# driver bugchecked twice (0x116, STATUS_INSUFFICIENT_RESOURCES) during long runs.
$psi.EnvironmentVariables["OLLAMA_GPU_OVERHEAD"] = "1610612736"
$proc = [System.Diagnostics.Process]::Start($psi)

for ($i = 0; $i -lt 30; $i++) {
    try {
        $v = (Invoke-WebRequest -UseBasicParsing http://localhost:11434/api/version -TimeoutSec 2).Content
        Write-Host "Ollama $v running as pid $($proc.Id)"
        exit 0
    } catch { Start-Sleep -Seconds 1 }
}
throw "Ollama did not answer on port 11434"
