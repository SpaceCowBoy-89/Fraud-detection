#!/bin/bash

echo "================================================"
echo "Installing Advanced Pattern Detection Features"
echo "================================================"
echo ""

echo "📦 Installing new dependencies..."
echo ""

# Install PyOD (anomaly detection)
echo "Installing PyOD..."
pip3 install 'pyod>=1.1.0' --quiet

# Install SHAP (explainability)
echo "Installing SHAP..."
pip3 install 'shap>=0.42.0' --quiet

# Install Alibi Detect (drift detection)
echo "Installing Alibi Detect..."
pip3 install 'alibi-detect>=0.11.0' --quiet

echo ""
echo "✅ Installation complete!"
echo ""
echo "================================================"
echo "New Features Added:"
echo "================================================"
echo ""
echo "  14. 🤖 Advanced Anomaly Detection (PyOD)"
echo "      - Finds fraud patterns rules might miss"
echo "      - Uses 3 ML algorithms + consensus"
echo ""
echo "  15. 📉 Drift Monitoring (Pattern Changes)"
echo "      - Alerts when fraud patterns evolve"
echo "      - Validates detection rules still work"
echo ""
echo "================================================"
echo "Quick Start:"
echo "================================================"
echo ""
echo "1. Start the web dashboard:"
echo "   python run.py"
echo "   Open http://localhost:5050 and run analysis from the UI"
echo ""
echo "2. Pattern discovery and anomaly views:"
echo "   Dashboard → Effectiveness / Analytics tabs"
echo ""
echo "3. Scheduled pipeline (optional):"
echo "   python scheduler.py   # or docker compose scheduler service"
echo ""
echo "📖 Read the guide:"
echo "   cat ADVANCED_FEATURES_GUIDE.md"
echo ""
echo "================================================"
echo "Ready to go! 🚀"
echo "================================================"
