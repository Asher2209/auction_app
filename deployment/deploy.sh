#!/bin/bash

# ChainBid Production Deployment Script

set -e  # Exit on error

REPO_URL="https://github.com/Asher2209/auction_app.git"
DEPLOY_DIR="/opt/chainbid"
APP_USER="chainbid"
BACKUP_DIR="/backups/chainbid"

echo "================================"
echo "ChainBid Deployment"
echo "================================"

# Step 1: Pre-flight checks
echo "[1/8] Running pre-flight checks..."
if [ ! -f .env.production ]; then
    echo "ERROR: .env.production not found"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found"
    exit 1
fi

# Step 2: Backup current deployment
echo "[2/8] Backing up current deployment..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
if [ -d "$DEPLOY_DIR" ]; then
    cp -r "$DEPLOY_DIR" "$BACKUP_DIR/chainbid_$TIMESTAMP"
    echo "Backup saved to $BACKUP_DIR/chainbid_$TIMESTAMP"
fi

# Step 3: Pull latest code
echo "[3/8] Pulling latest code from repository..."
cd "$DEPLOY_DIR"
git pull origin main

# Step 4: Install dependencies
echo "[4/8] Installing dependencies..."
python3 -m pip install -r requirements.txt --quiet

# Step 5: Database migration
echo "[5/8] Running database migrations..."
python3 -m flask db upgrade

# Step 6: Stop current application
echo "[6/8] Stopping application..."
systemctl stop chainbid || true

# Step 7: Start new application
echo "[7/8] Starting application..."
systemctl start chainbid

# Step 8: Verify deployment
echo "[8/8] Verifying deployment..."
sleep 5
if curl -f http://localhost:5000/api/health/live > /dev/null 2>&1; then
    echo ""
    echo "================================"
    echo "✓ Deployment Successful!"
    echo "================================"
    echo "Application is running"
else
    echo ""
    echo "================================"
    echo "✗ Deployment Failed!"
    echo "================================"
    echo "Application health check failed"
    exit 1
fi
