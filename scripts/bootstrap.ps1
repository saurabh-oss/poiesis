# Poiesis bootstrap for Windows. Run from the repo root after `docker compose up -d`.
#
# Ollama runs natively on the Windows host (not in Compose) so it gets direct CUDA
# access. This script talks to it over HTTP on the host, builds the poiesis-* model
# variants with a context window the agents' prompts actually fit into, and then
# indexes your portfolio into the knowledge graph.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-EnvValue([string]$key) {
  $line = Select-String -Path (Join-Path $repoRoot ".env") -Pattern "^$key=(.*)$" -ErrorAction SilentlyContinue
  if ($line) { return $line.Matches[0].Groups[1].Value.Trim() }
  return ""
}

# ---- 1. Host prerequisites --------------------------------------------------
$profileName = Get-EnvValue "POIESIS_LLM_PROFILE"
if (-not $profileName) { $profileName = "local" }

if ($profileName -eq "local") {
  Write-Host "Checking Ollama on the host..." -ForegroundColor Cyan
  $ollamaHost = [Environment]::GetEnvironmentVariable("OLLAMA_HOST", "User")
  if ($ollamaHost -ne "0.0.0.0:11434") {
    Write-Host "  OLLAMA_HOST is '$ollamaHost', not '0.0.0.0:11434'." -ForegroundColor Yellow
    Write-Host "  Ollama will bind to localhost only and containers will not reach it." -ForegroundColor Yellow
    Write-Host "  Fix: setx OLLAMA_HOST 0.0.0.0:11434  then fully quit Ollama from the tray." -ForegroundColor Yellow
  }

  try {
    $tags = Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 5
    Write-Host "  Ollama up, $($tags.models.Count) models present" -ForegroundColor Green
  } catch {
    throw "Ollama is not answering on localhost:11434. Start it, then rerun this script."
  }

  # ---- 2. Base models -------------------------------------------------------
  # The models named in .env, plus the embedding model the knowledge graph uses.
  # Qwen3.6 35B-A3B is ~23 GB per variant; the first pull takes a while.
  Write-Host "Pulling the models named in .env (~55 GB the first time)..." -ForegroundColor Cyan
  $wanted = @()
  foreach ($key in @("POIESIS_MODEL_REASONING", "POIESIS_MODEL_CODING", "POIESIS_MODEL_FAST",
                     "POIESIS_MODEL_EMBED", "POIESIS_MODEL_VISION")) {
    $m = (Get-EnvValue $key) -replace "^ollama/", ""
    if ($m -and ($wanted -notcontains $m)) { $wanted += $m }
  }
  if (-not $wanted) { $wanted = @("qwen3.6:35b-a3b", "qwen3.6:35b-a3b-coding", "nomic-embed-text", "gemma4:12b") }
  foreach ($m in $wanted) {
    Write-Host "  pulling $m"
    ollama pull $m
  }
  # The context window is sent with every request (POIESIS_LOCAL_NUM_CTX), so no
  # Modelfile variants are needed any more.
}

# ---- 4. Orchestrator --------------------------------------------------------
Write-Host "Waiting for the orchestrator..." -ForegroundColor Cyan
$health = $null
$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
  try {
    $health = Invoke-RestMethod http://localhost:8080/health -TimeoutSec 3
    Write-Host "  orchestrator up (profile: $($health.llm_profile), pack: $($health.pack))" -ForegroundColor Green
    break
  } catch { Start-Sleep -Seconds 5 }
}
if (-not $health) { throw "The orchestrator never became healthy. Check: docker compose logs orchestrator" }

if ($profileName -eq "local") {
  Write-Host "Verifying the container can reach host Ollama..." -ForegroundColor Cyan
  $reachable = docker compose exec -T orchestrator python -c "import httpx,sys; sys.exit(0 if httpx.get('http://host.docker.internal:11434/api/tags', timeout=5).status_code==200 else 1)"
  if ($LASTEXITCODE -eq 0) {
    Write-Host "  container reaches host Ollama" -ForegroundColor Green
  } else {
    Write-Host "  container CANNOT reach host Ollama." -ForegroundColor Red
    Write-Host "  Set OLLAMA_HOST=0.0.0.0:11434, restart Ollama, and allow ollama.exe" -ForegroundColor Red
    Write-Host "  through Windows Firewall on private networks." -ForegroundColor Red
  }
}

# ---- 5. Portfolio -----------------------------------------------------------
Write-Host "Indexing your portfolio into the knowledge graph..." -ForegroundColor Cyan
docker compose run --rm indexer
if ($LASTEXITCODE -ne 0) {
  Write-Host "  Indexing finished with problems - see above. The Architect agent will" -ForegroundColor Yellow
  Write-Host "  have nothing to reuse until this succeeds." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Ready. Open http://localhost:3000" -ForegroundColor Green
Write-Host "Knowledge graph browser: http://localhost:7474  (neo4j / poiesisdev)"
