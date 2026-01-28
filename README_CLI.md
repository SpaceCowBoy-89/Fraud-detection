# Fraud Detection CLI System

A comprehensive command-line interface for detecting fraud in affiliate marketing accounts with API integration and advanced email pattern detection.

## Features

✅ **Rich CLI Interface** - Beautiful terminal UI with colors, progress bars, and emojis
✅ **API Integration** - Fetch data directly from affiliate tracking API
✅ **Advanced Fraud Detection** - Multiple pattern detection algorithms:
   - Name-number patterns (e.g., john43murphy5398@gmail.com)
   - Repeated word patterns (dynamic detection)
   - Scrambled email patterns (improved detection)
   - Written number patterns (e.g., emillytwo@gmail.com)
   - Suspicious name detection
   - Domain concentration analysis

✅ **Database Storage** - SQLite database with proper indexing
✅ **Flexible Filtering** - Filter by POV verified, user agent, chargeback count, credit count, site code, and more
✅ **Incremental Updates** - Fetch only new data since last sync
✅ **Reporting & Alerts** - High-risk account alerts and detailed reports
✅ **Configuration Management** - Customizable risk thresholds and detection weights

## Installation

### 1. Install Dependencies

```bash
cd /Users/pat/fraud-detection
pip install -r requirements.txt
```

### 2. Configure API Key

First time setup:

```bash
python3 cli_fraud_detection.py
```

Navigate to **Settings (Option 4)** → **Set API Key (Option 1)**

Or set as environment variable:
```bash
export FRAUD_DETECTION_API_KEY="your_api_key_here"
```

## Usage

### Start the CLI

```bash
python3 cli_fraud_detection.py
```

### Main Menu Options

```
1. 🔄 Fetch New Data from API
   - Fetch leads (free signups) or sales (paid transactions)
   - Select date range (7 days, 30 days, custom, or incremental)
   - Apply optional filters:
     * POV Verified status
     * Site Code
     * User Agent
     * Chargeback Count
     * Credit Count
     * Webmaster Code
     * Email Domain
     * Campaign

2. 🔍 Run Fraud Detection Analysis
   - Analyze new data only or re-analyze everything
   - Automatically detects patterns across all emails
   - Saves results to database

3. 📈 View Fraud Detection Reports
   - See risk distribution (High/Medium/Low)
   - View total payouts at risk
   - Export to CSV

4. ⚙️  Configure Settings
   - Set/update API key
   - Adjust risk thresholds
   - Modify detection weights
   - Manage whitelisted affiliates

5. 📊 View Dashboard Metrics
   - Total accounts analyzed
   - Fraud detection rate
   - Revenue at risk
   - Latest statistics

6. 🚨 Check High-Risk Alerts
   - View top 10 high-risk accounts
   - Quick access to flagged emails
   - Sorted by risk score

7. 📁 Export Reports
   - Export to CSV, Excel
   - Automatic file naming based on date

8. 🧪 Test Mode (Analyze Single Email)
   - Test fraud detection on any email
   - Instant risk score and flag analysis
   - Perfect for validating new patterns

9. 📖 View Logs
   - Recent activity logs
   - Error tracking
   - API request history
```

## Typical Workflow

### Daily Fraud Check

```
1. Start CLI: python3 cli_fraud_detection.py
2. Select Option 1 (Fetch New Data)
   - Choose "Both" (leads + sales)
   - Select "Since last fetch" (incremental)
   - Skip filters (or apply as needed)
3. Select Option 2 (Run Fraud Detection)
   - Choose "New data only"
4. Select Option 6 (Check High-Risk Alerts)
   - Review flagged accounts
   - Create Asana tasks for investigation
5. Select Option 7 (Export Reports)
   - Save for documentation
```

### Weekly Pattern Review

```
1. Select Option 5 (View Dashboard Metrics)
   - Check fraud detection rate trends
2. Select Option 3 (View Reports)
   - Analyze new fraud patterns
   - Identify repeated word clusters
3. Update CLAUDE.md with new patterns discovered
```

## Database Structure

The CLI automatically creates and manages a SQLite database with the following tables:

- **paid** - Paid transactions (sales)
- **free** - Free signups (leads)
- **fraud_results** - Fraud detection analysis results
- **fetch_history** - API fetch tracking

## Configuration

Configuration is stored in `config.json`:

```json
{
  "api_key": "your_api_key",
  "risk_thresholds": {
    "high": 50,
    "medium": 25
  },
  "detection_weights": {
    "excessive_dots": 25,
    "digit_suffix": 20,
    "scrambled_pattern": 35,
    "name_number_pattern": 40,
    "written_number": 25,
    "repeated_word": 35,
    "suspicious_name": 30
  },
  "ip_velocity_threshold": 10,
  "whitelisted_affiliates": []
}
```

## Optional Filters Available

### All Data Types
- **webmaster_code** - Filter by affiliate webmaster code
- **email_domain** - Filter by email domain (e.g., gmail.com)
- **campaign** - Filter by campaign ID
- **custom_http_user_agent** - Filter by browser/device user agent

### Leads Only
- **pov_verified** - Filter by email verification status (true/false)
- **site_code** - Filter by specific site code

### Sales Only
- **chargeback_count** - Minimum number of chargebacks
- **credit_count** - Minimum number of credits

## Advanced Features

### Incremental Data Fetching
The CLI tracks the last fetch date and automatically fetches only new data:
```
Select date range: 4. Since last fetch (incremental)
```

### Repeated Word Pattern Detection
The system dynamically finds words that appear >3 times across all emails:
- Finds patterns like "golding" appearing in 25 accounts
- Catches name inversions (hgolding, goldinghenry, etc.)
- No hardcoding needed - adapts to new fraud patterns

### Test Mode
Test any email without fetching data:
```
Option 8: Test Mode
Enter email: suspicious@example.com
→ Instant risk score and analysis
```

## Troubleshooting

### API Key Not Working
```
1. Check API key in config.json
2. Or set environment variable: export FRAUD_DETECTION_API_KEY="key"
3. Test connection in Settings menu
```

### No Data Returned
```
1. Check date range (may be no data in that period)
2. Verify filters aren't too restrictive
3. Check logs: Option 9 (View Logs)
```

### High Memory Usage
```
1. Use incremental fetching instead of large date ranges
2. Analyze in batches (new data only)
3. Consider PostgreSQL for large datasets
```

## File Structure

```
fraud-detection/
├── cli_fraud_detection.py   # Main CLI interface
├── database.py               # Database management
├── api_client.py             # API integration
├── config.py                 # Configuration management
├── config.json               # User configuration
├── affiliate_data.db         # SQLite database
├── scripts/
│   └── email_fraud_detector.py  # Fraud detection engine
├── reports/                  # Generated reports
└── fraud_detection.log       # Activity logs
```

## Performance Tips

1. **Use Incremental Fetching** - Only fetch new data since last run
2. **Filter Early** - Apply API filters to reduce data transfer
3. **Analyze New Data** - Only analyze unanalyzed records
4. **Index Optimization** - Database indexes are created automatically
5. **Batch Operations** - Process leads and sales separately for large datasets

## Integration with Existing Workflow

This CLI integrates with your existing fraud detection workflow:

1. **Replaces manual CSV exports** - API fetches data automatically
2. **Enhances email pattern detection** - Dynamic pattern discovery
3. **Stores historical data** - Track patterns over time
4. **Generates reports** - Same CSV format as before
5. **Asana integration ready** - Export high-risk accounts for task creation

## Support

For issues or questions:
1. Check logs: `fraud_detection.log`
2. Review CLAUDE.md for fraud patterns
3. Test single emails in Test Mode (Option 8)

## Future Enhancements

- [ ] Real-time webhook integration
- [ ] Asana API integration (auto-create tasks)
- [ ] IP geolocation analysis
- [ ] Card BIN clustering
- [ ] Machine learning model training
- [ ] Web dashboard interface
- [ ] Email notifications for critical alerts
