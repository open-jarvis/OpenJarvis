#!/usr/bin/env bash
# Setup script for WebChoreArena / WebArena standalone backends.
#
# WebArena images are distributed as pre-built tar files — they are NOT on
# any public Docker registry.  This script downloads the tars from the CMU
# mirror, loads them, and starts all six services.
#
# WARNING: The downloads are large (each image is several GB).  Run this on
# a machine with a fast connection and at least 100 GB of free disk space.
#
# Usage:
#   bash scripts/setup_webchorearena.sh              # download + start all
#   bash scripts/setup_webchorearena.sh --start      # start already-loaded images
#   bash scripts/setup_webchorearena.sh --stop       # stop all containers
#   bash scripts/setup_webchorearena.sh --status     # print container status
#   bash scripts/setup_webchorearena.sh --test        # curl-test all endpoints
#
# After the script completes, paste the printed export block into your shell
# before running the eval:
#   openjarvis-eval run -b webchorearena --agentic -m <model>
#
# Official setup docs:
#   https://github.com/web-arena-x/webarena/tree/main/environment_docker

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Host that external clients will use to reach the services.
# On the same machine: "localhost"
# On a remote server: its public IP or hostname
HOST="${WEBARENA_HOST:-localhost}"

# Port assignments (match WebArena defaults)
SHOPPING_PORT="${SHOPPING_PORT:-7770}"
SHOPPING_ADMIN_PORT="${SHOPPING_ADMIN_PORT:-7780}"
REDDIT_PORT="${REDDIT_PORT:-9999}"
GITLAB_PORT="${GITLAB_PORT:-8023}"
WIKIPEDIA_PORT="${WIKIPEDIA_PORT:-8888}"
MAP_PORT="${MAP_PORT:-3000}"

# Where to store downloaded tars and the Wikipedia ZIM file
DOWNLOAD_DIR="${WEBARENA_DOWNLOAD_DIR:-$HOME/.cache/webarena-images}"

# CMU mirror (fast, no auth required)
BASE_URL="http://metis.lti.cs.cmu.edu/webarena-images"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------
require_docker() {
    if ! command -v docker &>/dev/null; then
        error "Docker is not installed. Install it from https://docs.docker.com/engine/install/"
        exit 1
    fi
    if ! docker info &>/dev/null; then
        if sudo docker info &>/dev/null 2>&1; then
            warn "Docker requires sudo — consider adding yourself to the docker group:"
            warn "  sudo usermod -aG docker \$USER && newgrp docker"
            docker() { sudo docker "$@"; }
            export -f docker
        else
            error "Docker daemon is not running. Start it with: sudo systemctl start docker"
            exit 1
        fi
    fi
}

container_running() { docker ps --filter "name=^${1}$" --filter "status=running" -q | grep -q .; }
container_exists()  { docker ps -a --filter "name=^${1}$" -q | grep -q .; }
image_loaded()      { docker images -q "$1" | grep -q .; }

download_if_missing() {
    local url="$1" dest="$2"
    if [[ -f "$dest" ]]; then
        info "$(basename "$dest") already downloaded — skipping."
    else
        info "Downloading $(basename "$dest") ..."
        info "  Source: $url"
        mkdir -p "$(dirname "$dest")"
        wget -c --show-progress -O "$dest" "$url" \
            || { rm -f "$dest"; error "Download failed: $url"; exit 1; }
    fi
}

wait_for_http() {
    local url="$1" label="$2" retries="${3:-36}" delay="${4:-5}"
    info "Waiting for $label at $url ..."
    for i in $(seq 1 "$retries"); do
        if curl -fsS --max-time 4 "$url" -o /dev/null 2>/dev/null; then
            info "$label is UP."
            return 0
        fi
        echo -n "  attempt $i/$retries ..."
        sleep "$delay"
    done
    warn "$label did not become ready. Check logs: docker logs $label"
    return 1
}

# ---------------------------------------------------------------------------
# --stop
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--stop" ]]; then
    require_docker
    step "Stopping WebArena containers"
    for c in shopping shopping_admin forum gitlab wikipedia; do
        if container_exists "$c"; then
            docker rm -f "$c" && info "Removed $c" || warn "Could not remove $c"
        fi
    done
    # Map uses docker compose
    if [[ -d "$HOME/openstreetmap-website" ]]; then
        cd "$HOME/openstreetmap-website" && docker compose stop && cd - >/dev/null
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--status" ]]; then
    require_docker
    echo ""
    docker ps -a --filter "name=shopping" \
        --filter "name=forum" \
        --filter "name=gitlab" \
        --filter "name=wikipedia" \
        --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    exit 0
fi

# ---------------------------------------------------------------------------
# --test
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--test" ]]; then
    step "Testing all WebArena endpoints"
    pass=0; fail=0
    check() {
        local label="$1" url="$2"
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
        if [[ "$code" == "200" || "$code" == "301" || "$code" == "302" ]]; then
            echo -e "  ${GREEN}✓${NC} $label ($code)"
            pass=$((pass + 1))
        else
            echo -e "  ${RED}✗${NC} $label ($code)"
            fail=$((fail + 1))
        fi
    }
    check "Shopping     :${SHOPPING_PORT}"       "http://${HOST}:${SHOPPING_PORT}"
    check "Shopping Admin:${SHOPPING_ADMIN_PORT}" "http://${HOST}:${SHOPPING_ADMIN_PORT}/admin"
    check "Reddit/Forum  :${REDDIT_PORT}"         "http://${HOST}:${REDDIT_PORT}"
    check "GitLab        :${GITLAB_PORT}"         "http://${HOST}:${GITLAB_PORT}"
    check "Wikipedia     :${WIKIPEDIA_PORT}"      "http://${HOST}:${WIKIPEDIA_PORT}"
    check "Map           :${MAP_PORT}"            "http://${HOST}:${MAP_PORT}"
    echo ""
    echo -e "  Passed: ${GREEN}$pass${NC}  Failed: ${RED}$fail${NC}"
    exit $(( fail > 0 ? 1 : 0 ))
fi

# ---------------------------------------------------------------------------
# --start  (skip downloads, just start already-loaded images)
# ---------------------------------------------------------------------------
START_ONLY=false
if [[ "${1:-}" == "--start" ]]; then
    START_ONLY=true
fi

# ---------------------------------------------------------------------------
# Main: download + load + start
# ---------------------------------------------------------------------------
require_docker

if [[ "$START_ONLY" == false ]]; then
    step "Downloading WebArena image tars to $DOWNLOAD_DIR"
    echo "  (This may take a while — each image is several GB)"
    echo ""

    download_if_missing \
        "$BASE_URL/shopping_final_0712.tar" \
        "$DOWNLOAD_DIR/shopping_final_0712.tar"

    download_if_missing \
        "$BASE_URL/shopping_admin_final_0719.tar" \
        "$DOWNLOAD_DIR/shopping_admin_final_0719.tar"

    download_if_missing \
        "$BASE_URL/postmill-populated-exposed-withimg.tar" \
        "$DOWNLOAD_DIR/postmill-populated-exposed-withimg.tar"

    download_if_missing \
        "$BASE_URL/gitlab-populated-final-port8023.tar" \
        "$DOWNLOAD_DIR/gitlab-populated-final-port8023.tar"

    # Wikipedia uses a public kiwix image + a .zim data file
    download_if_missing \
        "$BASE_URL/wikipedia_en_all_maxi_2022-05.zim" \
        "$DOWNLOAD_DIR/wikipedia_en_all_maxi_2022-05.zim"

    step "Loading Docker images (this can take several minutes per image)"

    for tar in shopping_final_0712 shopping_admin_final_0719 \
               postmill-populated-exposed-withimg gitlab-populated-final-port8023; do
        if image_loaded "$tar"; then
            info "Image '$tar' already loaded — skipping."
        else
            info "Loading $tar ..."
            docker load --input "$DOWNLOAD_DIR/${tar}.tar"
        fi
    done
fi

# ---------------------------------------------------------------------------
# Start containers
# ---------------------------------------------------------------------------
step "Starting containers"

start_or_resume() {
    local name="$1"; shift
    if container_running "$name"; then
        info "$name already running."
    elif container_exists "$name"; then
        info "Resuming $name ..."
        docker start "$name"
    else
        info "Creating $name ..."
        docker run "$@"
    fi
}

start_or_resume shopping \
    --name shopping -p "${SHOPPING_PORT}:80" -d shopping_final_0712

start_or_resume shopping_admin \
    --name shopping_admin -p "${SHOPPING_ADMIN_PORT}:80" -d shopping_admin_final_0719

start_or_resume forum \
    --name forum -p "${REDDIT_PORT}:80" -d postmill-populated-exposed-withimg

# GitLab needs its own start command (internal port is 8023)
start_or_resume gitlab \
    --name gitlab -d -p "${GITLAB_PORT}:8023" \
    gitlab-populated-final-port8023 /opt/gitlab/embedded/bin/runsvdir-start

# Wikipedia: public kiwix image + the downloaded ZIM file
start_or_resume wikipedia \
    --name wikipedia \
    --volume="${DOWNLOAD_DIR}:/data" \
    -p "${WIKIPEDIA_PORT}:80" \
    -d ghcr.io/kiwix/kiwix-serve:3.3.0 wikipedia_en_all_maxi_2022-05.zim

# Map: openstreetmap-website docker compose (complex — skip unless AMI)
if [[ -d "$HOME/openstreetmap-website" ]]; then
    info "Starting Map via docker compose ..."
    cd "$HOME/openstreetmap-website" && docker compose start && cd - >/dev/null
else
    warn "Map service not found at ~/openstreetmap-website."
    warn "On an AWS AMI this is pre-installed. For local setup see:"
    warn "  https://github.com/web-arena-x/webarena/tree/main/environment_docker"
fi

# ---------------------------------------------------------------------------
# Post-start configuration (Magento needs its hostname set)
# ---------------------------------------------------------------------------
step "Configuring services (wait 60s for Magento to boot)"
sleep 60

info "Configuring Shopping base URL → http://${HOST}:${SHOPPING_PORT}"
docker exec shopping /var/www/magento2/bin/magento \
    setup:store-config:set --base-url="http://${HOST}:${SHOPPING_PORT}" || true
docker exec shopping mysql -u magentouser -pMyPassword magentodb -e \
    "UPDATE core_config_data SET value='http://${HOST}:${SHOPPING_PORT}/' WHERE path='web/secure/base_url';" || true
docker exec shopping /var/www/magento2/bin/magento cache:flush || true

info "Configuring Shopping Admin base URL → http://${HOST}:${SHOPPING_ADMIN_PORT}"
docker exec shopping_admin /var/www/magento2/bin/magento \
    setup:store-config:set --base-url="http://${HOST}:${SHOPPING_ADMIN_PORT}" || true
docker exec shopping_admin mysql -u magentouser -pMyPassword magentodb -e \
    "UPDATE core_config_data SET value='http://${HOST}:${SHOPPING_ADMIN_PORT}/' WHERE path='web/secure/base_url';" || true
docker exec shopping_admin php /var/www/magento2/bin/magento config:set \
    admin/security/password_is_forced 0 || true
docker exec shopping_admin php /var/www/magento2/bin/magento config:set \
    admin/security/password_lifetime 0 || true
docker exec shopping_admin /var/www/magento2/bin/magento cache:flush || true

info "Configuring GitLab external URL → http://${HOST}:${GITLAB_PORT}"
info "  (GitLab takes ~5 min to boot — reconfigure will run in background)"
(
    sleep 240
    docker exec gitlab update-permissions 2>/dev/null || true
    docker exec gitlab sed -i \
        "s|^external_url.*|external_url 'http://${HOST}:${GITLAB_PORT}'|" \
        /etc/gitlab/gitlab.rb
    docker exec gitlab gitlab-ctl reconfigure
    info "GitLab reconfigured."
) &

# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
step "Waiting for services"
wait_for_http "http://${HOST}:${SHOPPING_PORT}"       "Shopping"       30 5 || true
wait_for_http "http://${HOST}:${SHOPPING_ADMIN_PORT}" "Shopping Admin" 30 5 || true
wait_for_http "http://${HOST}:${REDDIT_PORT}"         "Reddit/Forum"   30 5 || true
wait_for_http "http://${HOST}:${WIKIPEDIA_PORT}"      "Wikipedia"      30 5 || true
wait_for_http "http://${HOST}:${GITLAB_PORT}"         "GitLab"         60 5 || true
if [[ -d "$HOME/openstreetmap-website" ]]; then
    wait_for_http "http://${HOST}:${MAP_PORT}" "Map" 30 5 || true
fi

# ---------------------------------------------------------------------------
# Print env vars
# ---------------------------------------------------------------------------
step "Done — export these before running the eval"
echo ""
cat <<ENV
export SHOPPING="http://${HOST}:${SHOPPING_PORT}"
export SHOPPING_ADMIN="http://${HOST}:${SHOPPING_ADMIN_PORT}/admin"
export REDDIT="http://${HOST}:${REDDIT_PORT}"
export GITLAB="http://${HOST}:${GITLAB_PORT}"
export MAP="http://${HOST}:${MAP_PORT}"
export WIKIPEDIA="http://${HOST}:${WIKIPEDIA_PORT}"
ENV
echo ""
info "Then run the benchmark:"
echo "  openjarvis-eval run -b webchorearena --agentic -m <your-model>"
echo ""
info "To test all endpoints:  bash scripts/setup_webchorearena.sh --test"
info "To stop all services:   bash scripts/setup_webchorearena.sh --stop"
echo ""
