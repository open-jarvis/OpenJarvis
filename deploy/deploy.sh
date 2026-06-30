#!/bin/bash
set -euo pipefail

# OpenJarvis Production Deployment Script
# This script handles deployment to production infrastructure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOYMENT_ENV="${DEPLOYMENT_ENV:-production}"
DOCKER_REGISTRY="${DOCKER_REGISTRY:-registry.example.com}"
IMAGE_NAME="openjarvis"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    local required_commands=("docker" "docker-compose" "curl" "git")
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "Required command not found: $cmd"
            return 1
        fi
    done
    
    log_success "All prerequisites met"
}

# Load environment
load_environment() {
    log_info "Loading environment: $DEPLOYMENT_ENV"
    
    if [ ! -f "$PROJECT_ROOT/.env.$DEPLOYMENT_ENV" ]; then
        log_error "Environment file not found: .env.$DEPLOYMENT_ENV"
        return 1
    fi
    
    # shellcheck disable=SC1090
    source "$PROJECT_ROOT/.env.$DEPLOYMENT_ENV"
    log_success "Environment loaded"
}

# Build Docker image
build_image() {
    log_info "Building Docker image: ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
    
    cd "$PROJECT_ROOT"
    
    if ! docker build \
        -t "${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}" \
        -t "${DOCKER_REGISTRY}/${IMAGE_NAME}:latest" \
        -f Dockerfile \
        .; then
        log_error "Failed to build Docker image"
        return 1
    fi
    
    log_success "Docker image built successfully"
}

# Push Docker image
push_image() {
    log_info "Pushing Docker image to registry..."
    
    if ! docker push "${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"; then
        log_error "Failed to push Docker image"
        return 1
    fi
    
    if ! docker push "${DOCKER_REGISTRY}/${IMAGE_NAME}:latest"; then
        log_error "Failed to push latest tag"
        return 1
    fi
    
    log_success "Docker image pushed to registry"
}

# Run database migrations
run_migrations() {
    log_info "Running database migrations..."
    
    if ! docker-compose exec -T openjarvis \
        python -m alembic upgrade head; then
        log_error "Database migrations failed"
        return 1
    fi
    
    log_success "Database migrations completed"
}

# Deploy services
deploy_services() {
    log_info "Deploying services..."
    
    cd "$PROJECT_ROOT"
    
    if ! docker-compose -f docker-compose.yml \
        -p openjarvis-${DEPLOYMENT_ENV} \
        up -d; then
        log_error "Failed to deploy services"
        return 1
    fi
    
    log_success "Services deployed successfully"
}

# Health checks
run_health_checks() {
    log_info "Running health checks..."
    
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
            log_success "Health check passed"
            return 0
        fi
        
        attempt=$((attempt + 1))
        log_info "Health check attempt $attempt/$max_attempts..."
        sleep 2
    done
    
    log_error "Health checks failed after $max_attempts attempts"
    return 1
}

# Smoke tests
run_smoke_tests() {
    log_info "Running smoke tests..."
    
    if ! docker-compose exec -T openjarvis \
        pytest tests/ -v --tb=short -m "not slow"; then
        log_error "Smoke tests failed"
        return 1
    fi
    
    log_success "Smoke tests passed"
}

# Rollback function
rollback() {
    log_warning "Rolling back deployment..."
    
    # Get previous image version
    local previous_tag="$(git describe --tags --abbrev=0 HEAD^)"
    
    if [ -z "$previous_tag" ]; then
        log_error "Cannot determine previous version for rollback"
        return 1
    fi
    
    IMAGE_TAG="$previous_tag"
    
    if docker-compose -f docker-compose.yml \
        -p openjarvis-${DEPLOYMENT_ENV} \
        up -d; then
        log_success "Rollback completed to version: $previous_tag"
        return 0
    else
        log_error "Rollback failed"
        return 1
    fi
}

# Main deployment flow
main() {
    log_info "Starting OpenJarvis deployment to $DEPLOYMENT_ENV"
    
    # Pre-deployment checks
    check_prerequisites || { rollback; exit 1; }
    load_environment || { rollback; exit 1; }
    
    # Build and push
    build_image || { rollback; exit 1; }
    push_image || { rollback; exit 1; }
    
    # Deploy
    deploy_services || { rollback; exit 1; }
    
    # Post-deployment verification
    sleep 10  # Give services time to start
    run_health_checks || { rollback; exit 1; }
    run_migrations || { rollback; exit 1; }
    run_smoke_tests || { rollback; exit 1; }
    
    log_success "Deployment completed successfully!"
    log_info "Application is running at: http://$DOMAIN"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            DEPLOYMENT_ENV="$2"
            shift 2
            ;;
        --tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        --registry)
            DOCKER_REGISTRY="$2"
            shift 2
            ;;
        --rollback)
            rollback
            exit $?
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main deployment
main "$@"
