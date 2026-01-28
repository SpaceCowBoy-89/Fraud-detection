# Quick Start Guide - Fraud Detection CLI

## 5-Minute Setup

### Step 1: Install Dependencies (1 minute)
```bash
cd /Users/pat/fraud-detection
pip3 install -r requirements.txt
```

### Step 2: Start the CLI (10 seconds)
```bash
python3 cli_fraud_detection.py
```

### Step 3: Configure API Key (1 minute)
```
Main Menu → Select Option 4 (Settings)
→ Select Option 1 (Set API Key)
→ Paste your API key
→ Press B to go back
```

### Step 4: Fetch Your First Data (2 minutes)
```
Main Menu → Select Option 1 (Fetch Data)
→ Select "3" (Both leads and sales)
→ Select "2" (Last 30 days)
→ Skip all filters (just press 'n' for each)
→ Wait for data to download
```

### Step 5: Run Fraud Detection (1 minute)
```
Main Menu → Select Option 2 (Run Fraud Detection)
→ Select "1" (New data only)
→ Wait for analysis to complete
```

### Step 6: View Results (30 seconds)
```
Main Menu → Select Option 6 (Check High-Risk Alerts)
→ See your top fraud accounts!
```

## Done! 🎉

You now have:
- ✅ Data synced from API
- ✅ Fraud patterns detected
- ✅ High-risk accounts identified
- ✅ Reports ready for export

## What's Next?

### Daily Routine (2-3 minutes)
1. **Morning**: Fetch new data (Option 1, incremental)
2. **Morning**: Run fraud detection (Option 2, new data only)
3. **Review**: Check high-risk alerts (Option 6)
4. **Action**: Create Asana tasks for flagged accounts

### Weekly Review (15 minutes)
1. View Dashboard Metrics (Option 5)
2. Export full reports (Option 7)
3. Analyze new fraud patterns
4. Update detection rules if needed

## Common First-Time Issues

### ❌ "API key not configured"
**Solution**: Go to Settings (Option 4) and set your API key

### ❌ "No data returned"
**Solution**:
- Check your date range (maybe no transactions in that period)
- Verify API key is correct
- Check if filters are too restrictive

### ❌ "Module 'rich' not found"
**Solution**: Run `pip3 install rich` or `pip3 install -r requirements.txt`

### ❌ "No high-risk accounts found"
**Solution**:
- This is actually good news! Your accounts are clean
- Or try lowering the risk threshold in Settings

## Testing the System

Want to test before using real data?

### Test Mode
```
Main Menu → Option 8 (Test Mode)
→ Enter test email: john43murphy5398@gmail.com
→ See instant fraud analysis
```

Try these test emails:
- `john43murphy5398@gmail.com` - Should score 95 (Name-Number pattern)
- `emillytwo81@gmail.com` - Should score 95+ (Written number + repeated)
- `vbfghbvdfg@gmail.com` - Should score 70+ (Scrambled)
- `normal.user@gmail.com` - Should score 0 (Clean)

## Tips for Success

1. **Start Small**: Fetch 7 days of data first, not 30 days
2. **Use Incremental**: Always use "Since last fetch" for daily updates
3. **Filter Smart**: Use filters to reduce API data transfer
4. **Review Daily**: Check high-risk alerts every morning
5. **Track Patterns**: Note which patterns catch real fraud vs false positives

## Need Help?

1. **View Logs**: Option 9 shows recent activity
2. **Check README**: Full documentation in README_CLI.md
3. **Test Single Email**: Option 8 for quick testing
4. **Review CLAUDE.md**: Fraud pattern documentation

## Advanced: Customize Detection

### Adjust Risk Thresholds
```
Settings → Option 2 (Change risk thresholds)
→ Set High Risk threshold (default: 50)
→ Set Medium Risk threshold (default: 25)
```

### Why Adjust?
- **Too many false positives**: Increase thresholds (60/35)
- **Missing fraud**: Decrease thresholds (40/20)
- **Focus on severe cases**: Increase high threshold (70+)

## Integration with Existing Workflow

This CLI **replaces**:
- ❌ Manual CSV exports from affiliate platform
- ❌ Manual file uploads
- ❌ Running scripts with specific filenames

This CLI **enhances**:
- ✅ Automatic data fetching
- ✅ Historical data storage
- ✅ Pattern evolution tracking
- ✅ Incremental updates

This CLI **keeps**:
- ✅ Same fraud detection algorithms
- ✅ Same CSV report formats
- ✅ Same Asana workflow
- ✅ Same BookStack documentation process

## Your First Week

**Day 1**: Setup + Fetch 30 days of data
**Day 2-5**: Daily incremental fetches + review alerts
**Day 6**: Weekly review + export reports
**Day 7**: Adjust thresholds based on false positive rate

After Week 1, you'll have:
- 📊 Baseline fraud detection rate
- 🎯 Optimized risk thresholds
- 📈 Historical pattern data
- ⚡ 5-minute daily workflow

## Ready to Start?

```bash
python3 cli_fraud_detection.py
```

Welcome to automated fraud detection! 🚀
