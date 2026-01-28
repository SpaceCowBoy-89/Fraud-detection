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
echo "1. Run fraud detection first:"
echo "   python3 cli_fraud_detection.py"
echo "   Choose Option 2 (Run Fraud Detection)"
echo ""
echo "2. Try anomaly detection:"
echo "   Choose Option 14 (Advanced Anomaly Detection)"
echo ""
echo "3. Check for drift:"
echo "   Choose Option 15 (Drift Monitoring)"
echo ""
echo "📖 Read the guide:"
echo "   cat ADVANCED_FEATURES_GUIDE.md"
echo ""
echo "================================================"
echo "Ready to go! 🚀"
echo "================================================"
