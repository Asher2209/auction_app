#!/bin/bash

# ChainBid Rollback Script

set -e

BACKUP_DIR="/backups/chainbid"
DEPLOY_DIR="/opt/chainbid"

echo "================================"
echo "ChainBid Rollback"
echo "================================"

# Get latest backup
LATEST_BACKUP=$(ls -t "$BACKUP_DIR" | head -1)

if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No backup found"
    exit 1
fi

echo "Rolling back to: $LATEST_BACKUP"

# Stop application
echo "[1/4] Stopping application..."
systemctl stop chainbid

# Restore backup
echo "[2/4] Restoring backup..."
rm -rf "$DEPLOY_DIR"
cp -r "$BACKUP_DIR/$LATEST_BACKUP" "$DEPLOY_DIR"

# Start application
echo "[3/4] Starting application..."
systemctl start chainbid

# Verify
echo "[4/4] Verifying rollback..."
sleep 5

if curl -f http://localhost:5000/api/health/live > /dev/null 2>&1; then
    echo ""
    echo "================================"
    echo "✓ Rollback Successful!"
    echo "================================"
else
    echo ""
    echo "================================"
    echo "✗ Rollback Failed!"
    echo "================================"
    exit 1
fi
