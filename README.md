# Affiliate Fraud Detection System

Automated fraud detection and prevention system for affiliate marketing programs.

## Quick Start

1. **Setup**:
   ```bash
   cd ~/fraud-detection
   pip install pandas numpy
   ```

2. **Place your data**:
   - Export `Leads.csv` from affiliate tracking platform
   - Place in `data/` directory

3. **Run analysis**:
   ```bash
   python scripts/email_fraud_detector.py
   ```

4. **Review results**:
   - Check `reports/email_fraud_report_HIGH_RISK.csv` for priority cases
   - Full analysis in `reports/email_fraud_report.csv`

## What It Detects

The system automatically flags suspicious affiliate accounts based on:

- **Email patterns**: Excessive dots, digit suffixes, scrambled usernames
- **Domain concentration**: Traffic clustering from suspicious domains
- **Theme clustering**: Related email themes suggesting coordinated fraud
- **Risk scoring**: 0-100 scale with actionable thresholds

## Project Structure

```
fraud-detection/
├── scripts/          # Python fraud detection scripts
├── data/            # CSV exports (not committed to git)
├── reports/         # Generated analysis reports
├── docs/            # Additional documentation
├── CLAUDE.md        # Detailed guide for Claude Code
└── README.md        # This file
```

## Fraud Patterns Detected

### High Priority
- **Email validation timing** (< 60 seconds after account creation)
- **Domain concentration** (>90% from same non-major provider)
- **Scrambled emails** (random character patterns)

### Medium Priority
- **Email patterns** (multiple dots, digit suffixes)
- **Theme clustering** (real estate, construction, crypto, finance)

## Future Enhancements

- Cross-reference Leads and Sales data
- Geolocation mismatch detection
- Payment card clustering analysis
- Real-time API integration (currently uses CSV exports)

## Documentation

See `CLAUDE.md` for comprehensive documentation including:
- Complete fraud pattern catalog
- Data source details
- API integration roadmap
- Customization guide

## Support

This system is designed to work with Claude Code. Start a new session in the `fraud-detection` directory and Claude will automatically load context from `CLAUDE.md`.
