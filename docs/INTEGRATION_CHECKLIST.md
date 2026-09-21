# Integration Checklist - Quick Reference

## ✅ Pre-Integration (Before You Start)

### 1. Technical Requirements
- [ ] Confirm platform backend language (Python? Node.js? PHP?)
- [ ] Identify database type (PostgreSQL? MySQL? SQLite?)
- [ ] Check Python version compatibility (need Python 3.7+)
- [ ] Review authentication system (how will fraud module access it?)
- [ ] Map out where hooks will go (account creation, email validation)

### 2. Stakeholder Alignment
- [ ] Get buy-in from engineering team
- [ ] Secure dev resources (40-60 hours backend, 20-30 hours frontend)
- [ ] Brief operations team on upcoming changes
- [ ] Set success metrics with management
- [ ] Schedule kickoff meeting

### 3. API Access Status
- [ ] Request timestamps from developer (registration + email validation)
- [ ] Request billing "Used By" data
- [ ] Request admin event logs (image uploads)
- [ ] Timeline from developer for API access
- [ ] Fallback plan if API delayed

---

## 🔧 Phase 1: Foundation (Weeks 1-2)

### Database Setup
- [ ] Add `fraud_results` table to platform database
- [ ] Add `fraud_outcomes` table
- [ ] Add `business_metrics` table (optional)
- [ ] Add `eda_cache` table (optional)
- [ ] Add `industry_benchmarks` table (optional)
- [ ] Create indexes (duid, risk_score, analyzed_at)
- [ ] Test database connection from fraud module

### Code Setup
- [ ] Install Python dependencies in platform environment
  ```bash
  pip install pandas numpy openpyxl requests rich reportlab
  ```
- [ ] Copy fraud detection modules to platform codebase
  - `scripts/email_fraud_detector.py`
  - `scripts/data_preprocessor.py`
  - `scripts/eda_analyzer.py` (optional)
  - `scripts/business_analytics.py` (optional)
  - `database.py`
  - `config.py`
- [ ] Create `config.json` with risk scores
- [ ] Test import: `from scripts.email_fraud_detector import EmailFraudDetector`

### Configuration
- [ ] Set up environment variables (database path, API keys)
- [ ] Configure logging (where do fraud detection logs go?)
- [ ] Set up error monitoring (Sentry, New Relic, etc.)
- [ ] Define risk score thresholds (50 = high risk, 75 = critical)
- [ ] Configure house affiliates list

---

## 🔗 Phase 2: Core Integration (Weeks 3-4)

### Account Creation Hook
- [ ] Identify where accounts are created in codebase
- [ ] Add fraud detection call after account creation
- [ ] Pass all required fields (email, IP, affiliate, campaign, etc.)
- [ ] Store fraud result in `fraud_results` table
- [ ] Test: Create test account, verify fraud result saved
- [ ] Handle errors gracefully (don't block account creation if fraud detection fails)

**Code location to modify**: `_____________________`

### Email Validation Hook
- [ ] Identify where email validation happens
- [ ] Add fraud re-analysis with validation timestamp
- [ ] Implement 60-second rule check
- [ ] Update existing fraud result
- [ ] Test: Validate test account, verify updated risk score

**Code location to modify**: `_____________________`

### Error Handling
- [ ] Wrap fraud detection in try/catch (don't break account creation)
- [ ] Log errors to monitoring system
- [ ] Alert dev team if fraud detection is failing
- [ ] Fallback: Skip fraud detection if module unavailable

---

## 🎨 Phase 3: UI Integration (Weeks 5-6)

### Admin Panel - Account Details
- [ ] Add fraud risk badge/panel to account details page
- [ ] Display: Risk score, flags, analyzed timestamp
- [ ] Show risk breakdown (which rules triggered)
- [ ] Add "Mark as False Positive" button
- [ ] Add "Confirm Fraud" button
- [ ] Link to related accounts (shared card, similar patterns)

**File to modify**: `_____________________`

### Admin Panel - Account List
- [ ] Add "High Risk" filter to account list
- [ ] Add risk score column (sortable)
- [ ] Add visual indicator (🔴 red dot for high risk)
- [ ] Bulk actions: "Review Selected Accounts"

### Alert System
- [ ] Set up Slack webhook
- [ ] Implement alert function (send on high-risk detection)
- [ ] Test: Create high-risk account, verify Slack notification
- [ ] Add email alerts (optional)
- [ ] Configure alert thresholds (only alert if score >= 75)

**Slack webhook URL**: `_____________________`

---

## 📊 Phase 4: Reporting (Weeks 7-8)

### Embedded Dashboard
- [ ] Option A: Embed existing Flask dashboard via iframe
- [ ] Option B: Rebuild dashboard natively in platform UI
- [ ] Add "Fraud Detection" menu item in admin navigation
- [ ] Test: Access fraud dashboard, verify data displays

### Admin Homepage Widget
- [ ] Add "Fraud Alert" widget to admin homepage
- [ ] Display: High-risk accounts count, pending reviews
- [ ] Link to fraud dashboard
- [ ] Auto-refresh every 5 minutes

### Reports
- [ ] Add CSV export button (fraud results)
- [ ] Add PDF report generation (optional - uses pdf_generator.py)
- [ ] Schedule weekly fraud summary email (optional)
- [ ] Integrate with existing BI tools (Metabase, Kibana)

---

## 🧪 Phase 5: Testing (Week 9)

### Unit Tests
- [ ] Test fraud detection with sample accounts
- [ ] Test preprocessing with dirty data
- [ ] Test database writes (fraud_results, fraud_outcomes)
- [ ] Test alert system (Slack, email)

### Integration Tests
- [ ] Create 100 test accounts (various risk levels)
- [ ] Verify fraud detection runs for each
- [ ] Check fraud results saved correctly
- [ ] Verify alerts sent for high-risk accounts
- [ ] Test admin UI displays data correctly

### Load Tests
- [ ] Simulate 1000 accounts/hour
- [ ] Measure fraud detection latency (<500ms target)
- [ ] Check database performance (indexes working?)
- [ ] Monitor memory usage

### User Acceptance Testing (UAT)
- [ ] Operations team reviews high-risk accounts
- [ ] Test "Mark as False Positive" workflow
- [ ] Test "Confirm Fraud" workflow
- [ ] Gather feedback on UI/UX
- [ ] Make adjustments based on feedback

---

## 🚀 Phase 6: Launch (Week 10)

### Soft Launch (Week 10 - Parallel Run)
- [ ] Enable fraud detection in production
- [ ] Run in parallel with old manual process
- [ ] Compare results (integrated vs manual)
- [ ] Monitor for errors/bugs
- [ ] Adjust thresholds if needed

### Training
- [ ] Train operations team on new workflow
- [ ] Document SOPs (how to review fraud alerts)
- [ ] Create video tutorial (optional)
- [ ] Q&A session with team

### Full Launch (Week 11)
- [ ] Announce to team: fraud detection now live
- [ ] Retire old manual export workflow
- [ ] Monitor adoption metrics
- [ ] Celebrate wins! 🎉

### Post-Launch Monitoring (Week 12+)
- [ ] Track fraud prevention metrics weekly
- [ ] Adjust risk scores based on false positive rate
- [ ] Gather feedback from operations team
- [ ] Optimize performance (caching, indexing)

---

## 📋 Integration Contacts

**Technical Lead**: _____________________  
**Backend Developer**: _____________________  
**Frontend Developer**: _____________________  
**Operations Manager**: _____________________  
**Project Manager**: _____________________  

---

## 🎯 Success Metrics (Track These)

### Week 4
- [ ] Real-time detection working: YES / NO
- [ ] Fraud data in admin panel: YES / NO
- [ ] Manual exports eliminated: YES / NO

### Week 8
- [ ] Alerts operational: YES / NO
- [ ] Operations team trained: YES / NO
- [ ] Dashboard embedded: YES / NO

### Week 12
- [ ] Detection time: _____ hours (target: <4 hours)
- [ ] False positive rate: _____ % (target: <5%)
- [ ] Fraud prevented: $_____ (target: $50K+)
- [ ] Manual work time: _____ min/week (target: 0)
- [ ] Team adoption: _____ % (target: 100%)

---

## 🆘 Emergency Contacts

**If fraud detection breaks**:
1. Check logs: `_____________________`
2. Disable feature flag: `_____________________`
3. Contact: `_____________________`
4. Rollback plan: `_____________________`

**If false positives spike**:
1. Check risk score config: `config.json`
2. Review recent rule changes
3. Temporarily increase thresholds
4. Analyze flagged accounts for patterns

---

## 📞 Questions to Answer Before Starting

1. **Architecture**: Embedded module, REST API, or hybrid?
   - **Answer**: _____________________

2. **Database**: Shared with platform or separate?
   - **Answer**: _____________________

3. **Authentication**: How will fraud module access user sessions?
   - **Answer**: _____________________

4. **Deployment**: Same server as platform or separate?
   - **Answer**: _____________________

5. **Monitoring**: What tools do you use? (Sentry, Datadog, etc.)
   - **Answer**: _____________________

6. **Timeline**: When do you want to start integration?
   - **Answer**: _____________________

7. **Resources**: Who's available to work on this?
   - **Answer**: _____________________

---

**Last Updated**: January 25, 2026

**Ready to integrate?** Use this checklist to track progress! ✅
