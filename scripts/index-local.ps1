# Index a repo that lives on this laptop rather than on GitHub.
# Usage: .\scripts\index-local.ps1 -Path C:\src\meridian -Name "Meridian"
param(
  [Parameter(Mandatory=$true)][string]$Path,
  [Parameter(Mandatory=$true)][string]$Name
)
docker compose run --rm -v "${Path}:/local:ro" indexer --local /local --name "$Name"
