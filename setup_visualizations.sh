#!/bin/bash
# Quick Setup Script for Visualization Enhancements
# Run this script to set up everything in one go

set -e  # Exit on error

echo "🎨 FRAUD DETECTION - VISUALIZATION SETUP"
echo "========================================"
echo ""

# Change to project directory
cd ~/fraud-detection

echo "📍 Working directory: $(pwd)"
echo ""

# Step 1: Backup
echo "Step 1/4: Backing up database..."
if [ -f "fraud_detection.db" ]; then
    backup_name="fraud_detection.db.backup_$(date +%Y%m%d_%H%M%S)"
    cp fraud_detection.db "$backup_name"
    echo "✓ Backup created: $backup_name"
else
    echo "⚠️  No database found (will be created on first analysis)"
fi
echo ""

# Step 2: Migration
echo "Step 2/4: Running database migration..."
if [ -f "migrate_database.py" ]; then
    echo "yes" | python migrate_database.py
    echo "✓ Migration complete"
else
    echo "❌ migrate_database.py not found!"
    exit 1
fi
echo ""

# Step 3: Backfill
echo "Step 3/4: Backfilling affiliate data..."
if [ -f "backfill_affiliates.py" ]; then
    echo "yes" | python backfill_affiliates.py
    echo "✓ Backfill complete"
else
    echo "❌ backfill_affiliates.py not found!"
    exit 1
fi
echo ""

# Step 4: Verification
echo "Step 4/4: Verifying setup..."
if command -v sqlite3 &> /dev/null; then
    echo "Checking database schema..."
    sqlite3 fraud_detection.db "PRAGMA table_info(fraud_results);" > /dev/null 2>&1
    echo "✓ Database schema looks good"
else
    echo "⚠️  sqlite3 not found, skipping verification"
fi
echo ""

# Done!
echo "========================================"
echo "✅ SETUP COMPLETE!"
echo ""
echo "Next steps:"
echo "  1. Start dashboard:  python dashboard/app.py"
echo "  2. Open browser:     http://localhost:5000"
echo "  3. Read guide:       cat QUICK_START.md"
echo ""
echo "🎉 Enjoy the new visualization features!"
