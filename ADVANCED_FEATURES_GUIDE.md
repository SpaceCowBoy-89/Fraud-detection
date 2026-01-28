# Advanced Pattern Detection Features - Quick Start Guide

This guide covers the newly added advanced pattern detection capabilities that enhance your fraud detection system with machine learning-based anomaly detection and drift monitoring.

## 🚀 New Features Overview

### 1. **Advanced Anomaly Detection (Option 14)**
Uses unsupervised machine learning to find fraud patterns that rule-based detection might miss.

### 2. **Drift Monitoring (Option 15)**
Monitors changes in fraud patterns over time to alert when detection rules need updating.

---

## 📦 Installation

First, install the new dependencies:

```bash
cd ~/fraud-detection
pip install -r requirements.txt
```

This will install:
- `pyod>=1.1.0` - Anomaly detection library (already installed)
- `shap>=0.42.0` - Explainability framework
- `alibi-detect>=0.11.0` - Drift detection library

---

## 🤖 Feature 1: Advanced Anomaly Detection

### What It Does

Runs **3 different anomaly detection algorithms** on your fraud results:
- **Isolation Forest**: Fast, tree-based anomaly detection
- **KNN (K-Nearest Neighbors)**: Finds outliers based on distance from neighbors
- **LOF (Local Outlier Factor)**: Detects anomalies in varying-density clusters

The system then identifies accounts flagged by **2 or more algorithms** (consensus) for high-confidence anomaly detection.

### When To Use

- ✅ **After running fraud detection** (Option 2)
- ✅ When you want to find **hidden fraud patterns** missed by rules
- ✅ To **validate** your rule-based detection
- ✅ When investigating **unusual account patterns**

### How To Use

1. **Run fraud detection first** (Menu Option 2)
2. **Select Option 14** - Advanced Anomaly Detection
3. **Choose data type**: Free, Paid, or Both
4. **Review results**:
   - See how many anomalies each algorithm found
   - View **CONSENSUS** - accounts flagged by 2+ algorithms
   - See newly discovered potential frauds
5. **Export findings** if prompted

### Interpreting Results

**Example Output:**
```
Anomaly Detection Results:

Algorithm              Anomalies Detected    % of Total
─────────────────────────────────────────────────────────
IsolationForest        342                   8.5%
KNN                    289                   7.2%
LOF                    318                   7.9%
CONSENSUS (2+ agree)   156                   3.9%
```

**What This Means:**
- 156 accounts flagged by at least 2 algorithms = **high-confidence anomalies**
- These accounts have low risk scores from rules but unusual patterns detected by ML

**Newly Discovered Frauds:**
```
⚠️  FOUND 23 POTENTIAL FRAUDS MISSED BY RULES!

Email                          Rule Risk    Anomaly Score    Payout
─────────────────────────────────────────────────────────────────────
john.smith123@gmail.com        35           8.42             $45.00
sarah.jones@yahoo.com          28           7.89             $38.50
...
```

**Action:** Investigate these accounts manually!

### Best Practices

- ✅ Run weekly to catch evolving fraud patterns
- ✅ Export and investigate all consensus anomalies
- ✅ Compare with your high-risk list to find gaps
- ✅ Update rules based on newly discovered patterns

### Interactive Visualizations

After running anomaly detection, you can open an **interactive browser dashboard** with 4 key visualizations:

**1. Algorithm Detection Comparison**
- Bar chart showing how many anomalies each algorithm detected
- Compare IsolationForest, KNN, LOF, and CONSENSUS results
- Hover to see exact counts and percentages

**2. Consensus vs Individual Algorithms**
- Scatter plot of risk score vs algorithm agreement
- Color-coded by consensus flag (red = flagged by 2+ algorithms)
- Hover to see email, risk score, and number of algorithms in agreement

**3. ML vs Rule-Based Risk Scores**
- Scatter plot comparing rule-based risk with ML anomaly scores
- Red points = newly discovered frauds (low rule risk, high ML risk)
- Dashed lines show thresholds (x=50 for high risk, y=0 for anomaly threshold)
- Hover to see full account details

**4. Newly Discovered Fraud Distribution**
- Box plots showing anomaly score distributions by algorithm
- Only includes accounts missed by rules but caught by ML
- Shows mean and standard deviation

**All visualizations are:**
- ✅ Fully interactive (zoom, pan, hover)
- ✅ Downloadable as PNG
- ✅ Saved to `reports/visualizations/`
- ✅ Shareable via HTML file

---

## 📉 Feature 2: Drift Monitoring

### What It Does

Detects if fraud patterns have **changed over time** by comparing:
- **Reference period** (historical baseline, e.g., 30-90 days ago)
- **Current period** (recent data, e.g., last 7-30 days)

Uses statistical tests to determine if the distribution of fraud indicators has significantly changed.

### When To Use

- ✅ **Weekly or monthly** - Set up regular monitoring
- ✅ When fraud rates suddenly **increase or decrease**
- ✅ Before **major rule updates** - validate current rules still work
- ✅ After **seasonal changes** (holidays, promotions)

### How To Use

1. **Select Option 15** - Drift Monitoring
2. **Choose reference period**:
   - 30 days (quick baseline)
   - 60 days (more stable)
   - 90 days (most reliable)
3. **Choose current period**:
   - 7 days (weekly check)
   - 14 days (bi-weekly)
   - 30 days (monthly)
4. **Review results**

### Interpreting Results

**No Drift Detected (Good!):**
```
✓ No Significant Drift Detected

Fraud patterns remain stable.
Current detection rules are still effective.

Metric                 Value
─────────────────────────────────
Drift Detected         NO ✓
P-Value                0.1234
Significance Level     0.05 (5%)
Reference Period       1,234 records
Current Period         456 records
```

**P-Value > 0.05** = No significant change ✅

---

**Drift Detected (Action Required!):**
```
⚠️  DRIFT DETECTED!

Fraud patterns have significantly changed!
Consider updating your detection rules.

Metric                 Value
─────────────────────────────────
Drift Detected         YES ⚠️
P-Value                0.0123
Significance Level     0.05 (5%)
Reference Period       1,234 records
Current Period         456 records
```

**P-Value < 0.05** = Significant change detected ⚠️

### What To Do When Drift Detected

**Recommended Actions:**
1. **Review recent fraud cases** to identify new patterns
2. **Update detection rules** to catch new fraud techniques
3. **Run anomaly detection** (Option 14) to find new patterns
4. **Increase monitoring frequency** (weekly → daily)
5. **Check for external factors**:
   - New affiliate source
   - Marketing campaign changes
   - Seasonal patterns

### Drift History

The system tracks all drift checks:
```
Recent Drift History:

Date                  Drift        P-Value
─────────────────────────────────────────────
2025-01-15 14:30      ✓ NO        0.1234
2025-01-08 10:15      ✓ NO        0.0987
2025-01-01 09:00      ⚠️ YES      0.0234
2024-12-25 11:45      ✓ NO        0.1567
```

Use this to track pattern stability over time.

### Interactive Visualizations

After running drift monitoring, you can open an **interactive browser dashboard** with 4 key visualizations:

**1. Drift History Timeline**
- Timeline showing all previous drift checks
- X marks = drift detected, circles = no drift
- Color-coded: red (drift) vs green (stable)
- Hover to see exact date, drift status, and p-value

**2. P-Value Trend**
- Line chart tracking p-values over time
- Area fill shows proximity to significance threshold
- Red dashed line at 0.05 (significance threshold)
- Values below line = drift detected
- Hover to see detailed statistics

**3. Risk Score Distribution Comparison**
- Overlaid histograms comparing reference vs current periods
- Blue = reference period (historical baseline)
- Red = current period (recent data)
- Shows if risk score patterns have shifted

**4. Pattern Shift Analysis**
- Box plots comparing key features across periods
- Shows risk_score, flag_count, and pov_seconds
- Side-by-side comparison of reference (blue) vs current (red)
- Displays median, quartiles, and outliers

**All visualizations are:**
- ✅ Fully interactive (zoom, pan, hover)
- ✅ Downloadable as PNG
- ✅ Saved to `reports/visualizations/`
- ✅ Shareable via HTML file

---

## 🎯 Recommended Workflow

### **Weekly Routine:**

**Monday Morning:**
1. Run **Drift Monitoring** (Option 15)
   - Compare last 60 days vs last 7 days
   - If drift detected → Investigate immediately

2. Run **Advanced Anomaly Detection** (Option 14)
   - Analyze all new fraud results
   - Export newly discovered frauds
   - Add to investigation queue

3. Review findings and update rules if needed

---

## 💡 Understanding the Algorithms

### Anomaly Detection Methods

#### **Isolation Forest**
- **How it works**: Randomly splits data; anomalies are easier to isolate
- **Best for**: General-purpose anomaly detection
- **Speed**: Very fast
- **Strengths**: Works well with high-dimensional data

#### **KNN (K-Nearest Neighbors)**
- **How it works**: Measures distance to nearest neighbors
- **Best for**: Detecting outliers in dense regions
- **Speed**: Medium
- **Strengths**: Simple, interpretable

#### **LOF (Local Outlier Factor)**
- **How it works**: Compares local density to neighbors
- **Best for**: Varying-density clusters
- **Speed**: Slower but thorough
- **Strengths**: Finds subtle anomalies

#### **Consensus**
- **What it is**: Accounts flagged by 2+ algorithms
- **Why use it**: Higher confidence, lower false positives
- **Recommended**: Always investigate consensus anomalies first

---

### Drift Detection Method

Uses **Kolmogorov-Smirnov test** and other statistical tests to compare distributions of:
- Risk scores
- Flag patterns
- Email complexity metrics
- POV timing
- Payout amounts

**P-Value Interpretation:**
- `p < 0.05` = Significant drift (update rules!)
- `0.05 ≤ p < 0.10` = Marginal drift (monitor closely)
- `p ≥ 0.10` = No drift (rules still effective)

---

## 📊 Integration with Existing Workflow

### Current Workflow
```
1. Fetch Data → 2. Run Fraud Detection → 3. View Reports → 4. Investigate
```

### Enhanced Workflow
```
1. Fetch Data
↓
2. Run Fraud Detection
↓
3. Advanced Anomaly Detection (NEW!) ← Find hidden fraud
↓
4. View Reports + Anomaly Exports
↓
5. Drift Monitoring (Weekly) ← Validate rules still work
↓
6. Investigate + Update Rules
```

---

## 🔧 Technical Details

### Features Used for Anomaly Detection
- Risk score
- Payout amount (log-transformed)
- Number of fraud flags triggered
- Email length, dot count, digit count
- POV verification timing
- Fast POV indicator

### Features Used for Drift Detection
- Risk score distribution
- Flag count distribution
- Email pattern metrics
- POV timing patterns
- Payout distributions

### Data Requirements
- **Minimum for anomaly detection**: 10 records
- **Minimum for drift detection**:
  - Reference: 100 records
  - Current: 20 records

---

## ⚠️ Troubleshooting

### "PyOD not available"
```bash
pip install pyod
```

### "Alibi Detect not available"
```bash
pip install alibi-detect
```

### "Insufficient data for anomaly detection"
- Need at least 10 fraud results
- Run fraud detection first (Option 2)

### "Insufficient reference data for drift detection"
- Need at least 100 records in reference period
- Choose longer reference window (60 or 90 days)
- Wait for more data to accumulate

---

## 📈 Expected Results

### Typical Anomaly Detection Results
- **10-15%** of accounts flagged as anomalies
- **3-5%** consensus anomalies (high confidence)
- **1-2%** newly discovered frauds (low rule risk, high ML risk)

### Typical Drift Detection Results
- **80%** of weekly checks: No drift
- **15%** of weekly checks: Marginal drift (monitor)
- **5%** of weekly checks: Significant drift (update rules)

---

## 🎓 Learning Resources

### Understanding Your Results

**"Why was this flagged as an anomaly?"**
The account's feature combination is statistically unusual compared to the majority of accounts.

**"Should I trust ML over rules?"**
No. Use ML to **complement** rules:
- Rules catch **known patterns** (high precision)
- ML catches **unknown patterns** (high recall)
- Together = comprehensive detection

**"How often should I check for drift?"**
- **Weekly**: If fraud patterns change frequently
- **Bi-weekly**: Standard recommendation
- **Monthly**: If patterns are very stable

---

## 📝 Next Steps

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Run fraud detection**: Generate some results to analyze
3. **Try anomaly detection** (Option 14): See what ML finds
4. **Set up weekly drift checks** (Option 15): Monitor pattern evolution
5. **Review and refine**: Update rules based on findings

---

## 💪 Pro Tips

1. **Combine with existing reports**: Cross-reference anomaly findings with high-risk reports
2. **Track drift over time**: Build a dashboard from drift_history.json
3. **Automate weekly checks**: Schedule drift detection via cron
4. **Document patterns**: When you find new fraud patterns via ML, document and add to rules
5. **Start conservative**: Focus on consensus anomalies first (higher confidence)

---

## 🆘 Support

If you encounter issues:
1. Check logs: `fraud_detection.log`
2. Verify data requirements are met
3. Ensure all dependencies installed
4. Review error messages for specific guidance

---

**Implemented:** January 2025
**Purpose:** Enhance fraud detection with ML-based pattern discovery
**Impact:** Find hidden fraud, monitor pattern evolution, improve detection accuracy
