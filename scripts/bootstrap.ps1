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
  Write-Host "Pulling base models (~20 GB the first time)..." -ForegroundColor Cyan
  foreach ($m in @("qwen2.5:14b-instruct", "qwen2.5-coder:14b", "qwen2.5:7b-instruct",
                   "nomic-embed-text", "llama3.2-vision:11b")) {
    Write-Host "  pulling $m"
    ollama pull $m
  }

  # ---- 3. poiesis-* variants ------------------------------------------------
  # The agent prompts carry a portfolio context block and whole file contents;
  # Ollama's 2k default truncates them silently, which reads as a stupid model.
  Write-Host "Building the poiesis-* variants with a larger context window..." -ForegroundColor Cyan
  $variants = @{
    "poiesis-reasoning" = "reasoning"
    "poiesis-coding"    = "coding"
    "poiesis-fast"      = "fast"
  }
  foreach ($name in $variants.Keys) {
    $modelfile = Join-Path $repoRoot "modelfiles\$($variants[$name])"
    Write-Host "  creating $name from $modelfile"
    ollama create $name -f $modelfile
  }
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
