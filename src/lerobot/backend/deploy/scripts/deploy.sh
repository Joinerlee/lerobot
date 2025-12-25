#!/bin/bash
# ============================================
# LeRobot Teleoperation - Deployment Script
# ============================================
# Usage:
#   ./deploy.sh              # Deploy
#   ./deploy.sh --rollback   # Rollback to previous version
#   ./deploy.sh --status     # Check status
#   ./deploy.sh --logs       # View logs
#   ./deploy.sh --stop       # Stop all services

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$DEPLOY_DIR")"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
ENV_FILE="$DEPLOY_DIR/.env"
BACKUP_DIR="$DEPLOY_DIR/backups"
MAX_BACKUPS=5

# ============================================
# Helper Functions
# ============================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_requirements() {
    log_info "Checking requirements..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi

    # Check .env file
    if [ ! -f "$ENV_FILE" ]; then
        log_warning ".env file not found"
        if [ -f "$DEPLOY_DIR/.env.example" ]; then
            log_info "Copying .env.example to .env"
            cp "$DEPLOY_DIR/.env.example" "$ENV_FILE"
            log_warning "Please edit .env file with your configuration"
            exit 1
        else
            log_error ".env.example not found"
            exit 1
        fi
    fi

    log_success "All requirements met"
}

check_aws_credentials() {
    # Only check if S3 is configured
    if grep -q "S3_BUCKET_NAME=." "$ENV_FILE" 2>/dev/null; then
        log_info "Checking AWS credentials..."

        if [ -z "$AWS_ACCESS_KEY_ID" ] && ! grep -q "AWS_ACCESS_KEY_ID=." "$ENV_FILE"; then
            log_warning "AWS_ACCESS_KEY_ID not set (S3 will not work)"
        fi

        if [ -z "$AWS_SECRET_ACCESS_KEY" ] && ! grep -q "AWS_SECRET_ACCESS_KEY=." "$ENV_FILE"; then
            log_warning "AWS_SECRET_ACCESS_KEY not set (S3 will not work)"
        fi
    fi
}

create_backup() {
    log_info "Creating backup..."

    mkdir -p "$BACKUP_DIR"

    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_NAME="backup_$TIMESTAMP"

    # Backup current images
    if docker compose -f "$COMPOSE_FILE" ps -q 2>/dev/null | grep -q .; then
        docker compose -f "$COMPOSE_FILE" images -q 2>/dev/null | while read image; do
            if [ -n "$image" ]; then
                docker save "$image" | gzip > "$BACKUP_DIR/${BACKUP_NAME}_image.tar.gz" 2>/dev/null || true
            fi
        done
    fi

    # Cleanup old backups
    ls -t "$BACKUP_DIR"/backup_*.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm

    log_success "Backup created: $BACKUP_NAME"
}

health_check() {
    log_info "Running health checks..."

    local max_attempts=30
    local attempt=1
    local backend_url="http://localhost:${BACKEND_PORT:-8000}/health"

    while [ $attempt -le $max_attempts ]; do
        if curl -sf "$backend_url" > /dev/null 2>&1; then
            log_success "Backend is healthy"
            return 0
        fi

        log_info "Waiting for backend... (attempt $attempt/$max_attempts)"
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Health check failed after $max_attempts attempts"
    return 1
}

# ============================================
# Main Commands
# ============================================

deploy() {
    log_info "Starting deployment..."

    check_requirements
    check_aws_credentials
    create_backup

    # Pull latest images
    log_info "Pulling latest images..."
    docker compose -f "$COMPOSE_FILE" pull

    # Build backend image
    log_info "Building backend image..."
    docker compose -f "$COMPOSE_FILE" build --no-cache backend

    # Start services
    log_info "Starting services..."
    docker compose -f "$COMPOSE_FILE" up -d

    # Health check
    if health_check; then
        log_success "Deployment completed successfully!"
        show_status
    else
        log_error "Deployment failed, rolling back..."
        rollback
        exit 1
    fi
}

rollback() {
    log_info "Rolling back to previous version..."

    # Find latest backup
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/backup_*_image.tar.gz 2>/dev/null | head -1)

    if [ -z "$LATEST_BACKUP" ]; then
        log_error "No backup found for rollback"
        exit 1
    fi

    log_info "Using backup: $LATEST_BACKUP"

    # Stop current services
    docker compose -f "$COMPOSE_FILE" down

    # Load backup image
    gunzip -c "$LATEST_BACKUP" | docker load

    # Start services
    docker compose -f "$COMPOSE_FILE" up -d

    if health_check; then
        log_success "Rollback completed successfully!"
    else
        log_error "Rollback failed, manual intervention required"
        exit 1
    fi
}

show_status() {
    log_info "Service Status:"
    echo ""
    docker compose -f "$COMPOSE_FILE" ps
    echo ""

    log_info "Resource Usage:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
        $(docker compose -f "$COMPOSE_FILE" ps -q) 2>/dev/null || true
}

show_logs() {
    local service="${1:-}"

    if [ -n "$service" ]; then
        docker compose -f "$COMPOSE_FILE" logs -f "$service"
    else
        docker compose -f "$COMPOSE_FILE" logs -f
    fi
}

stop_services() {
    log_info "Stopping all services..."
    docker compose -f "$COMPOSE_FILE" down
    log_success "All services stopped"
}

# ============================================
# Main
# ============================================

case "${1:-}" in
    --rollback)
        rollback
        ;;
    --status)
        show_status
        ;;
    --logs)
        show_logs "${2:-}"
        ;;
    --stop)
        stop_services
        ;;
    --help)
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  (none)       Deploy the application"
        echo "  --rollback   Rollback to previous version"
        echo "  --status     Show service status"
        echo "  --logs       View logs (optionally specify service)"
        echo "  --stop       Stop all services"
        echo "  --help       Show this help message"
        ;;
    *)
        deploy
        ;;
esac
