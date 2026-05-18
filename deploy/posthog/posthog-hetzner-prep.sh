#!/usr/bin/env bash
# posthog-hetzner-prep.sh — one-shot Hetzner Cloud server prep for
# OpenJarvis's self-hosted PostHog analytics backend.
#
# Run this on a fresh Ubuntu 22.04+ box (Hetzner CCX23 in Ashburn, or
# similar) after pointing the desired domain at it. Idempotent: safe
# to re-run if a step fails partway.
#
# Usage:
#   sudo bash posthog-hetzner-prep.sh analytics.openjarvis.ai you@openjarvis.ai
#
# After it finishes:
#   1. Visit https://<DOMAIN>/ and create the admin account.
#   2. Create project "OpenJarvis".
#   3. Settings → Project → grab the Project API Key (phc_…).
#   4. Update src/openjarvis/core/config.py AnalyticsConfig defaults:
#        host = "https://<DOMAIN>"
#        key  = "phc_<new>"
#   5. Ship a release. Frontend + backend + install.sh all read those
#      same defaults via load_config().
#
# Cost: ~$35/mo on Hetzner CCX23 (4 dedicated vCPU / 16 GB / 240 GB
# NVMe) in US-East. Add Hetzner Cloud Backups (+20%) for production.
#
# Retention: post-install, set 365 days in PostHog UI →
#   Settings → Data Management → Event ingestion → Data retention.

set -euo pipefail

# ---- args ----
if [[ $# -lt 2 ]]; then
    cat >&2 <<'USAGE'
posthog-hetzner-prep.sh: missing arguments.

Usage:
  sudo bash posthog-hetzner-prep.sh <domain> <admin_email>

Examples:
  sudo bash posthog-hetzner-prep.sh analytics.openjarvis.ai team@openjarvis.ai

The domain must already resolve to this box (DNS A record) before
the script runs — Let's Encrypt needs to reach this server on port 80.
USAGE
    exit 2
fi

DOMAIN="$1"
ADMIN_EMAIL="$2"

if [[ $EUID -ne 0 ]]; then
    echo "posthog-hetzner-prep.sh: must be run as root (use sudo)." >&2
    exit 1
fi

# ---- step 1: system prep ----
echo "[1/5] apt update + base packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    curl ufw ca-certificates gnupg \
    apt-transport-https software-properties-common

# ---- step 2: firewall ----
echo "[2/5] firewall (UFW): 22/80/443 only..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ---- step 3: swap (helps ClickHouse under load spikes) ----
echo "[3/5] swap..."
if [[ ! -f /swapfile ]]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    if ! grep -q "/swapfile" /etc/fstab; then
        echo "/swapfile none swap sw 0 0" >> /etc/fstab
    fi
else
    echo "    /swapfile already present"
fi

# ---- step 4: docker ----
echo "[4/5] docker..."
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
else
    echo "    docker already installed"
fi
systemctl enable --now docker

# ---- step 5: posthog hobby deploy ----
echo "[5/5] PostHog Hobby Deploy..."
echo
echo "    Domain:        $DOMAIN"
echo "    Admin email:   $ADMIN_EMAIL"
echo "    DNS A record:  verify it points to $(curl -fsS -m 5 https://api.ipify.org 2>/dev/null || echo "<this server>")"
echo

# PostHog's official one-liner. It writes a .env file with random
# secrets, configures Caddy with Let's Encrypt TLS for the domain,
# and brings up the full stack via docker-compose.
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/deploy-hobby)" -s -- \
    --domain "$DOMAIN" \
    --email "$ADMIN_EMAIL" || {
    echo
    echo "PostHog deploy script exited with an error. Common causes:"
    echo "  - DNS for $DOMAIN doesn't resolve to this server yet (wait + retry)"
    echo "  - Port 80 not reachable from the public internet (firewall / cloud SG)"
    echo "  - Out of disk on /var/lib/docker (need 20+ GB free)"
    echo
    exit 1
}

cat <<EOF

================================================================
PostHog is up at https://$DOMAIN/

Next steps:
  1. Open https://$DOMAIN/ in a browser.
  2. Create the first admin account (any email, your password).
  3. Create project "OpenJarvis".
  4. Settings → Project → Project API Key — copy the phc_… value.
  5. Update src/openjarvis/core/config.py AnalyticsConfig defaults:
        host = "https://$DOMAIN"
        key  = "phc_<the-new-key>"
  6. Settings → Data Management → set retention to 365 days.
  7. Settings → Recordings → confirm Session Replay is OFF (default).
  8. Ship a release of OpenJarvis with the new config defaults.

Operational notes:
  - Updates:    bash <(curl -fsSL https://raw.githubusercontent.com/posthog/posthog/HEAD/bin/upgrade-hobby)
  - Logs:       docker compose -f /home/posthog/posthog/docker-compose.hobby.yml logs -f
  - Disk usage: df -h          # bump VPS tier when /var/lib/docker > 70% full
  - Backups:    enable Hetzner Cloud Backups in the Hetzner console
================================================================
EOF
