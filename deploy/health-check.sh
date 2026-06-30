#!/bin/bash
set -euo pipefail

# OpenJarvis Production Health Check Script
# Monitors application and infrastructure health

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${LOG_FILE:-/var/log/openjarvis/health-check.log}"
ALERT_EMAIL="${ALERT_EMAIL:-admin@example.com}"
SLACK_WEBHOOK="${SLACK_WEBHOOK:-}"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

# Logging
log_message() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

# Health check functions
check_application() {
    log_message "INFO" "Checking application health..."
    
    if curl -sf http://localhost:8000/health > /dev/null; then
        log_message "INFO" "Application is healthy"
        return 0
    else
        log_message "ERROR" "Application health check failed"
        return 1
    fi
}

check_database() {
    log_message "INFO" "Checking database health..."
    
    if docker-compose exec -T postgres pg_isready -U openjarvis > /dev/null 2>&1; then
        log_message "INFO" "PostgreSQL is healthy"
    else
        log_message "ERROR" "PostgreSQL health check failed"
        return 1
    fi
    
    if docker-compose exec -T mongodb mongosh --eval "db.adminCommand('ping')" > /dev/null 2>&1; then
        log_message "INFO" "MongoDB is healthy"
    else
        log_message "ERROR" "MongoDB health check failed"
        return 1
    fi
    
    return 0
}

check_cache() {
    log_message "INFO" "Checking cache health..."
    
    if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
        log_message "INFO" "Redis is healthy"
        return 0
    else
        log_message "ERROR" "Redis health check failed"
        return 1
    fi
}

check_disk_space() {
    log_message "INFO" "Checking disk space..."
    
    local threshold=80
    local usage=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
    
    if [ "$usage" -gt "$threshold" ]; then
        log_message "WARNING" "Disk usage is $usage% (threshold: $threshold%)"
        return 1
    else
        log_message "INFO" "Disk usage is $usage%"
        return 0
    fi
}

check_memory() {
    log_message "INFO" "Checking memory usage..."
    
    local threshold=85
    local usage=$(free | awk 'NR==2 {printf("%.0f", $3/$2 * 100)}')
    
    if [ "$usage" -gt "$threshold" ]; then
        log_message "WARNING" "Memory usage is $usage% (threshold: $threshold%)"
        return 1
    else
        log_message "INFO" "Memory usage is $usage%"
        return 0
    fi
}

check_docker_containers() {
    log_message "INFO" "Checking Docker containers..."
    
    local required_containers=("openjarvis-app" "openjarvis-postgres" "openjarvis-redis" "openjarvis-mongodb")
    local failed=0
    
    for container in "${required_containers[@]}"; do
        if docker inspect "$container" > /dev/null 2>&1; then
            local status=$(docker inspect -f '{{.State.Status}}' "$container")
            if [ "$status" = "running" ]; then
                log_message "INFO" "Container $container is running"
            else
                log_message "ERROR" "Container $container is not running (status: $status)"
                failed=1
            fi
        else
            log_message "ERROR" "Container $container not found"
            failed=1
        fi
    done
    
    return $failed
}

# Alert function
send_alert() {
    local subject="$1"
    local message="$2"
    
    log_message "ERROR" "Alert: $subject - $message"
    
    if [ -n "$SLACK_WEBHOOK" ]; then
        curl -X POST "$SLACK_WEBHOOK" \
            -H 'Content-Type: application/json' \
            -d "{\"text\": \"🚨 $subject\n$message\"}" \
            || log_message "ERROR" "Failed to send Slack alert"
    fi
}

# Main health check
main() {
    log_message "INFO" "Starting health check..."
    
    local failed=0
    
    check_application || failed=1
    check_database || failed=1
    check_cache || failed=1
    check_docker_containers || failed=1
    check_disk_space || failed=1
    check_memory || failed=1
    
    if [ $failed -eq 0 ]; then
        log_message "INFO" "All health checks passed ✓"
        return 0
    else
        log_message "ERROR" "Some health checks failed ✗"
        send_alert "OpenJarvis Health Check Failed" "One or more health checks failed. Check logs for details."
        return 1
    fi
}

main "$@"
