# OpenJarvis Production Deployment Guide

## Overview
This deployment guide covers production deployment of OpenJarvis with full monitoring, logging, and high availability setup.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Load Balancer                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
    ┌───▼──┐      ┌───▼──┐     ┌───▼──┐
    │  App │      │  App │     │  App │  (3+ replicas)
    └───┬──┘      └───┬──┘     └───┬──┘
        │             │             │
        └─────────────┼─────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    │                 │                 │
┌───▼──────┐  ┌──────▼──┐  ┌───────────▼─┐
│ PostgreSQL│  │ MongoDB │  │    Redis    │
└────┬─────┘  └─────┬───┘  └────┬────────┘
     │              │            │
     │   ┌──────────┼────────────┤
     │   │          │            │
┌────▼───▼──┐  ┌────▼────┐  ┌───▼────────┐
│Prometheus │  │Logstash │  │Elasticsearch
└────┬──────┘  └─────┬───┘  └────┬────────┘
     │              │             │
     └──────┬───────┴─────────────┤
            │                     │
        ┌───▼────────┐  ┌────────▼──┐
        │   Grafana  │  │   Kibana  │
        └────────────┘  └───────────┘
```

## Prerequisites

- Docker & Docker Compose (or Kubernetes cluster)
- 8GB+ RAM, 4+ CPU cores
- 50GB+ disk space
- PostgreSQL 16+
- MongoDB 7+
- Redis 7+

## Deployment Steps

### 1. Environment Configuration

```bash
# Copy the example configuration
cp .env.production.example .env.production

# Edit with your settings
nano .env.production
```

### 2. Docker Compose Deployment

```bash
# Create necessary directories
mkdir -p logs/openjarvis logs/elasticsearch

# Start all services
docker-compose up -d

# Verify services are running
docker-compose ps

# Check application health
curl http://localhost:8000/health
```

### 3. Kubernetes Deployment

```bash
# Create namespace
kubectl create namespace openjarvis

# Apply manifests
kubectl apply -f deploy/kubernetes-manifests.yml

# Verify deployment
kubectl get pods -n openjarvis
kubectl logs -n openjarvis deployment/openjarvis
```

### 4. Database Initialization

```bash
# Run migrations
docker-compose exec openjarvis python -m alembic upgrade head

# Seed initial data (if needed)
docker-compose exec openjarvis python -m openjarvis.db seed
```

### 5. Monitoring Setup

#### Prometheus
- Access: http://localhost:9090
- Alerts: Configured in `deploy/prometheus-rules.yml`

#### Grafana
- Access: http://localhost:3000
- Default credentials: admin/openjarvis-secure-password
- Import dashboards from `deploy/grafana-dashboards/`

#### Kibana
- Access: http://localhost:5601
- All logs indexed as `openjarvis-YYYY.MM.dd`

### 6. Health Checks

```bash
# Run deployment health check
bash deploy/health-check.sh

# Monitor application
docker-compose logs -f openjarvis

# Check database
docker-compose exec postgres pg_isready -U openjarvis

# Check Redis
docker-compose exec redis redis-cli ping

# Check MongoDB
docker-compose exec mongodb mongosh --eval "db.adminCommand('ping')"
```

## Scaling

### Docker Compose (Limited)
- Use multiple `docker-compose up` instances
- Implement load balancer (nginx, HAProxy)

### Kubernetes
```bash
# Scale deployment
kubectl scale deployment openjarvis -n openjarvis --replicas=5

# HPA automatically scales based on metrics
# Min: 3 replicas, Max: 10 replicas
# Triggers: CPU > 70%, Memory > 80%
```

## Updates & Rollbacks

### Deployment
```bash
# Build and deploy new version
bash deploy/deploy.sh --env production --tag v1.2.3

# With rollback on failure
bash deploy/deploy.sh --env production --tag v1.2.3 && echo "Success" || bash deploy/deploy.sh --rollback
```

### Rollback
```bash
# Automatic rollback
bash deploy/deploy.sh --rollback

# Manual rollback (Kubernetes)
kubectl rollout undo deployment/openjarvis -n openjarvis
```

## Security

### Network Security
- Use VPC/Network isolation
- Restrict database access
- Enable SSL/TLS for all services
- Use secrets management (HashiCorp Vault, AWS Secrets Manager)

### Database Security
- Change default passwords
- Enable encryption at rest
- Regular backups
- Audit logging enabled

### Application Security
- Enable CORS restrictions
- Rate limiting enabled
- JWT authentication
- Security headers configured

## Backup & Recovery

```bash
# PostgreSQL backup
docker-compose exec postgres pg_dump -U openjarvis openjarvis > backup.sql

# MongoDB backup
docker-compose exec mongodb mongodump --out /tmp/backup

# Redis backup
docker-compose exec redis redis-cli BGSAVE

# Restore from backups
docker-compose exec postgres psql -U openjarvis openjarvis < backup.sql
```

## Performance Tuning

### Database
- Connection pooling: 20-50 connections
- Query cache enabled
- Indexes optimized
- VACUUM/ANALYZE scheduled

### Redis
- Maxmemory policy: allkeys-lru
- Persistence: AOF enabled
- Replication for HA

### Application
- Worker processes: 4-8
- Request timeout: 30s
- Connection pool: 100-200

## Troubleshooting

### High Memory Usage
```bash
# Check container memory
docker stats openjarvis

# Clear cache
docker-compose exec redis redis-cli FLUSHALL

# Restart container
docker-compose restart openjarvis
```

### Database Connectivity
```bash
# Check PostgreSQL
docker-compose exec postgres psql -U openjarvis -c "SELECT version();"

# Check MongoDB
docker-compose exec mongodb mongosh --eval "db.version()"

# Check connections
docker-compose exec postgres psql -U openjarvis -c "SELECT count(*) FROM pg_stat_activity;"
```

### Slow Queries
```bash
# Enable query logging
docker-compose exec postgres psql -U openjarvis -c "SET log_min_duration_statement = 1000;"

# Check logs
docker logs openjarvis-postgres | grep "duration:"
```

## Support & Maintenance

- Monitor Grafana dashboards daily
- Review Kibana logs for errors
- Run health checks hourly
- Weekly database maintenance
- Monthly security updates

## References

- Docker Compose: https://docs.docker.com/compose/
- Kubernetes: https://kubernetes.io/
- Prometheus: https://prometheus.io/
- Grafana: https://grafana.com/
- Elasticsearch: https://www.elastic.co/
