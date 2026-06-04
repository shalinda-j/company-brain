#!/usr/bin/env bash
# ============================================================================
# Company Brain — one-command installer for a fresh Ubuntu droplet.
#
#   git clone <your-repo> company-brain && cd company-brain && ./install.sh
#
# What it does:
#   1. Installs Docker + Compose plugin if missing.
#   2. Creates .env from .env.example (if absent) and generates a strong API key.
#   3. Builds and starts the stack (Qdrant stays private, API on loopback).
#   4. Optionally enables HTTPS via Caddy if BRAIN_DOMAIN is set.
#   5. Prints how to connect.
# ============================================================================
set -euo pipefail

cyan() { printf "\033[36m%s\033[0m\n" "$1"; }
green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

cd "$(dirname "$0")"

# ---- 1. Docker ------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  cyan "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" 2>/dev/null || true
fi

DC="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
  else
    red "Docker Compose plugin not found. Please install it and re-run."
    exit 1
  fi
fi

# ---- 1b. Swap (small droplets) -------------------------------------------
# The embedding model needs RAM to load. On a small droplet (<3 GB) with no
# swap it can be OOM-killed on first start, so add a swapfile if missing.
TOTAL_KB="$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)"
HAS_SWAP="$(swapon --show 2>/dev/null | wc -l)"
if [ "${TOTAL_KB:-0}" -lt 3000000 ] && [ "${HAS_SWAP:-0}" -eq 0 ] && [ ! -f /swapfile ]; then
  cyan "Low RAM detected and no swap — adding a 2G swapfile..."
  sudo fallocate -l 2G /swapfile 2>/dev/null || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# ---- 2. .env --------------------------------------------------------------
gen_key() {
  python3 - "$1" <<'PY' 2>/dev/null || openssl rand -base64 32 | tr -d '/+=' | cut -c1-43
import secrets, sys
print(f"{secrets.token_urlsafe(32)}:{sys.argv[1]}")
PY
}

if [ ! -f .env ]; then
  cyan "Creating .env ..."
  cp .env.example .env
  KEY_CC="$(gen_key claude-code)"
  # Append a second key for a different agent so multi-agent works out of the box.
  RAW2="$(gen_key cursor)"
  KEYS="${KEY_CC},${RAW2}"
  # Portable in-place edit.
  if grep -q '^BRAIN_API_KEYS=' .env; then
    tmp="$(mktemp)"
    sed "s|^BRAIN_API_KEYS=.*|BRAIN_API_KEYS=${KEYS}|" .env > "$tmp" && mv "$tmp" .env
  else
    echo "BRAIN_API_KEYS=${KEYS}" >> .env
  fi
  green "Generated API keys (saved in .env)."
else
  yellow ".env already exists — leaving it untouched."
fi

# ---- 3 & 4. Start ---------------------------------------------------------
# shellcheck disable=SC1091
set +u; source .env 2>/dev/null || true; set -u

mkdir -p data

if [ -n "${BRAIN_DOMAIN:-}" ] && [ -n "${ACME_EMAIL:-}" ]; then
  cyan "BRAIN_DOMAIN set -> starting with HTTPS (Caddy) ..."
  $DC -f docker-compose.yml -f docker-compose.tls.yml up -d --build
  BASE="https://${BRAIN_DOMAIN}"
else
  cyan "Starting (API on 127.0.0.1:8000) ..."
  $DC up -d --build
  BASE="http://127.0.0.1:8000"
fi

cyan "Waiting for the brain to come up (first run downloads the embed model)..."
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:8000/health" >/dev/null 2>&1 || \
     { [ -n "${BRAIN_DOMAIN:-}" ] && curl -fsS "${BASE}/health" >/dev/null 2>&1; }; then
    green "Brain is healthy."
    break
  fi
  sleep 3
done

# ---- 5. Connection info ---------------------------------------------------
FIRST_KEY="$(grep '^BRAIN_API_KEYS=' .env | cut -d= -f2- | cut -d: -f1)"
echo
green "=============================================================="
green " Company Brain is running."
green "=============================================================="
echo " Base URL : ${BASE}"
echo " API key  : ${FIRST_KEY}   (agent: claude-code)"
echo
echo " Quick test:"
echo "   curl -s ${BASE}/health"
echo "   curl -s -X POST ${BASE}/save -H \"Authorization: Bearer ${FIRST_KEY}\" \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"content\":\"first memory\",\"title\":\"hello\"}'"
echo
yellow " SECURITY: if exposing remotely, set BRAIN_DOMAIN+ACME_EMAIL for HTTPS,"
yellow "           and lock the firewall:  ufw allow 80,443/tcp && ufw enable"
echo
echo " Connect an AI via MCP — see README.md (section 'Connect your AI')."
