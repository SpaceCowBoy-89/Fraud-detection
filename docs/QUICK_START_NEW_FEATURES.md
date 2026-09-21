# 🚀 Quick Start Guide - New Features

## Before You Start

**Prerequisites**:
- Python 3.7+ with packages installed (`pip install -r requirements.txt`)
- Existing database at `fraud_detection.db`
- Config file at `config.json`

**Database Migration** (Automatic):
When you first run the dashboard, the new tables will be automatically created:
- `business_metrics`
- `industry_benchmarks` (with dating site data)
- `eda_cache`

---

## 🌐 Testing the Dashboard

### Start the app
```bash
cd ~/fraud-detection
python run.py
```

Open **http://localhost:5050** (default port; see `PORT` env if different).

**Docker:**
```bash
docker compose up -d --build
```

### Test Data Explorer Tab
1. Click "Data Explorer" tab (new tab in navigation)
2. Select dataset: "Free Signups" or "Paid Sales"
3. Select date range: "All dates" for first test
4. Click "Analyze" button
5. Wait for results (5-30 seconds)
6. Review sections:
   - **Overview Statistics**: Record count, completeness, unique emails
   - **Data Distributions**: Interactive Plotly charts
   - **Fraud Correlations**: High-risk patterns by domain, amount, country
   - **Data Quality Issues**: Critical issues and warnings
   - **Statistical Outliers**: List of flagged accounts

**Interactive Features**:
- Hover over charts for details
- Click data points to explore (future feature)
- Click "Auto-Flag Outliers" (placeholder alert)
- Click "Export PDF" (placeholder - coming soon)

### Test Business Metrics in Overview Tab
1. Navigate to "Overview" tab
2. Scroll down past existing charts
3. Look for new "Financial Impact" section (future)
4. Check browser console (F12) for logged business metrics

**Console Output**:
```javascript
Business metrics loaded: {
  fraud_prevented: {total_prevented: 12450, count: 127, trend: 15},
  false_positive_rate: {rate: 2.8, count: 23, total_flagged: 820},
  risk_metrics: {...},
  industry_benchmarks: {...}
}
```

---

## 🔍 Testing Filters

### Date Range Filter (Dashboard - Analysis Panel)
1. Navigate to "Reports" tab
2. Locate "Run Fraud Analysis" panel
3. Expand "Date Range" dropdown
4. Select "Last 30 days"
5. Click "Analyze All Records"
6. Verify analysis only covers last 30 days

### Multi-Select Filters (Dashboard - Fetch/Analysis)
1. Navigate to "Fetch Data" panel
2. Click "Affiliate Codes" dropdown
3. Type to search, check multiple affiliates
4. Click "Campaigns" dropdown
5. Select multiple campaigns
6. Click "Start Fetch"
7. Confirm number of API calls (combinations)
8. Monitor progress bar

---

## 🐛 Troubleshooting

### "No module named 'pandas'"
```bash
pip install -r requirements.txt
```

### "Database is locked"
- Close duplicate dashboard or scheduler processes
- Wait 30 seconds and retry
- Check for stale processes: `ps aux | grep python`

### "No data to analyze"
- Run **Fetch** from the dashboard first
- Ensure you have records in database

### EDA shows 0 records
- Check date range filter - might be excluding all data
- Try "All dates" first
- Verify data exists: `sqlite3 fraud_detection.db "SELECT COUNT(*) FROM free;"`

### Charts not rendering (Dashboard)
- Check browser console (F12) for errors
- Verify Plotly.js loaded (check Network tab)
- Clear browser cache and refresh

### Industry benchmarks showing weird values
- Normal - using placeholder data until real values confirmed
- Dating industry averages: ~3% fraud rate, ~3.5% FP rate

---

## 📝 What to Look For

### Data Quality
- ✅ No syntax errors in console
- ✅ Charts render smoothly
- ✅ Tables display correctly
- ✅ Navigation works (back button, tabs)

### Performance
- ⏱️ EDA completes in <30 seconds for 10k records
- ⏱️ Business metrics load in <2 seconds
- ⏱️ Charts render without lag

### Functionality
- ✅ Analytics and Overview tabs load
- ✅ Date filters apply correctly
- ✅ EDA results display in UI
- ✅ No duplicate data in results

### User Experience
- 👍 Clear error messages
- 👍 Loading indicators during processing
- 👍 Success/failure toasts
- 👍 Intuitive navigation

---

## 📊 Sample Test Data

If you need test data, here's how to fetch:

```bash
python run.py
```

In the UI: **Fetch** → select free/paid and date range → run analysis → test **Data Explorer** and **Overview** metrics.

---

## ✅ Sign-off Checklist

Once you've tested everything, verify:

- [ ] Dashboard "Data Explorer" tab works
- [ ] Overview business metrics load
- [ ] EDA charts render in dashboard
- [ ] Date range filtering works
- [ ] Multi-select dropdowns work
- [ ] EDA API returns valid JSON (`POST /api/eda/run`)
- [ ] No console errors in dashboard
- [ ] Database tables created (check with sqlite3)
- [ ] Industry benchmarks seeded

---

## 🎉 Success!

If all checks pass, the implementation is **complete and working**!

**Next steps**:
1. Use in production workflow
2. Monitor for any edge cases
3. Gather feedback for improvements
4. Plan next features (PDF export, auto-flag, caching)

---

**Questions?** Check these files:
- `docs/WEEK_IMPLEMENTATION_SUMMARY.md` - Full implementation details
- `docs/WEEK_IMPLEMENTATION_TESTING.md` - Testing checklist
- `CLAUDE.md` - Updated user guide

**Support**: Review logs at `fraud_detection.log` for debugging

---

*Quick Start Guide - Version 1.0*
*Last Updated: January 25, 2026*
