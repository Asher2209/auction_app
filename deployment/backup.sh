#!/bin/bash

# Database Backup Script

BACKUP_DIR="/backups/chainbid"
DB_PATH="instance/auction.db"
RETENTION_DAYS=30

echo "Starting database backup..."

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Create timestamped backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/auction_$TIMESTAMP.db"

cp "$DB_PATH" "$BACKUP_FILE"
gzip "$BACKUP_FILE"

echo "✓ Backup created: $BACKUP_FILE.gz"

# Clean old backups
echo "Cleaning old backups (older than $RETENTION_DAYS days)..."
find "$BACKUP_DIR" -name "auction_*.db.gz" -mtime +$RETENTION_DAYS -delete

echo "✓ Backup complete"
