# Start all services (dev).
# Usage: .\scripts\dev.ps1 [-Detached]
param([switch]$Detached)

if ($Detached) {
    docker compose up -d --build
} else {
    docker compose up --build
}
