Fraud flag rules — ready to share
=================================

Open or attach these files (no dashboard required):

  FRAUD_FLAG_RULES.csv   — Excel / Google Sheets (rules + scores + triggers)
  FRAUD_FLAG_RULES.md    — Full guide for Fraud/Ops (same content, readable)

Regenerate after rule changes:

  cd ~/fraud-detection
  PYTHONPATH=scripts python3 scripts/fraud_flags_reference.py -f csv --use-config -o docs/FRAUD_FLAG_RULES.csv
  PYTHONPATH=scripts python3 scripts/fraud_flags_reference.py -f md --use-config -o docs/FRAUD_FLAG_RULES.md

Source definitions: fraud_flags_catalog.json + fraud_flags_extended.json
