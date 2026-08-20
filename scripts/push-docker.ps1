# Build and push to Docker Hub
# Usage: .\scripts\push-docker.ps1

param(
  [string]$Image = "xmchc/gofly",
  [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$full = "${Image}:${Tag}"
$ver = (Get-Content -Raw VERSION).Trim()
Write-Host "Building $full and ${Image}:${ver} ..."
docker context use desktop-linux | Out-Null
docker build --provenance=false --sbom=false --build-arg "APP_VERSION=$ver" -t $full -t "${Image}:${ver}" .
Write-Host "Pushing ${Image}:${ver} ..."
docker push "${Image}:${ver}"
Write-Host "Pushing $full ..."
docker push $full
Write-Host "Done: latest + $ver"
