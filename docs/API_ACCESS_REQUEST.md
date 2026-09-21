# API Access Request Template

## To: [Developer/Engineering Team]
**From**: [Your Name/Team]  
**Date**: [Date]  
**Subject**: API Access Request - Fraud Detection System Enhancement  
**Priority**: High (Business Impact)

---

## Executive Summary

We're requesting API access to automate our fraud detection system, which currently requires manual CSV exports. This will enable **real-time fraud detection** and reduce account review time from 24+ hours to **under 4 hours**.

**Business Impact**:
- Catch fraudulent accounts before first payout
- Reduce manual export time: ~90 min/week → 0 (100% automation)
- Enable real-time alerts for high-risk patterns
- Improve detection accuracy with timestamp-based rules

---

## Priority 1: Critical Data Fields (Highest Impact)

### 1. Account Registration Timestamp
**Field**: `account_creation_timestamp` or `registration_datetime`  
**Format**: ISO 8601 (e.g., `2025-01-25T14:30:00Z`)  
**Reason**: Calculate email validation timing (most critical fraud indicator)

**Current Limitation**: We use DUID as a proxy for registration date, but it's imprecise  
**Fraud Pattern**: Email validated within **60 seconds** of registration = 95% fraud rate  
**Business Value**: This alone could prevent 40% of fraud losses

**Example Use Case**:
```
Registration: 2025-01-25 14:30:00
Email Validation: 2025-01-25 14:30:15 (15 seconds)
→ AUTO-FLAG: High Risk (instant validation = bot)
```

---

### 2. Email Validation Timestamp
**Field**: `email_validation_timestamp` or `pov_verified_time`  
**Format**: ISO 8601  
**Reason**: Calculate validation speed (see above)

**Current Limitation**: Must manually export from internal platform  
**Fraud Pattern**: Human validation takes 2-10 minutes; bots validate in <60 seconds  
**Business Value**: Enables real-time bot detection

---

### 3. User Billing - Shared Credit Card Detection
**Field**: `credit_card_fingerprint` or `payment_method_id` (hashed/tokenized)  
**Related Field**: `used_by_accounts` (array of DUIDs using same card)  
**Reason**: Detect fraud rings using same payment method across multiple accounts

**Current Limitation**: No access to billing relationships  
**Fraud Pattern**: Same credit card used by 5+ accounts = coordinated fraud ring  
**Business Value**: Catch organized fraud networks (10-50 accounts per ring)

**Important**: Only include **"Used By"** relationships (confirmed same card), NOT "Possible Match" (fuzzy matching)

**Example Response**:
```json
{
  "duid": "384046981",
  "payment_method_fingerprint": "card_abc123xyz", // Hashed/tokenized
  "used_by_accounts": [
    "384046981",  // This account
    "384047001",  // Same card
    "384047125"   // Same card
  ],
  "shared_card_count": 3,
  "exclude_major_issuers": true  // Exclude: Bank of America, Chase, Capital One, Citi
}
```

**Security Note**: We only need a **hashed fingerprint** (not actual card numbers). Token format like `card_abc123xyz` is perfect.

**Filter Logic**: Exclude major card issuers (Bank of America, JP Morgan Chase, Capital One, Citi) to reduce false positives from family accounts.

---

### 4. Admin Log - Profile Image Upload Events
**Field**: `profile_image_upload_timestamp` or `has_uploaded_image`  
**Source**: Admin event logs  
**Reason**: Detect fake profiles using stolen/stock images

**Current Limitation**: No visibility into profile completion behavior  
**Fraud Pattern**: Accounts with no image upload or immediate upload = stock images  
**Business Value**: Enable reverse image search for fraud verification

**Example Response**:
```json
{
  "duid": "384046981",
  "profile_image_uploaded": true,
  "image_upload_timestamp": "2025-01-25T14:32:00Z",
  "image_upload_ip": "192.168.1.1",
  "upload_time_after_registration": 120  // seconds
}
```

**Fraud Patterns to Detect**:
- ❌ No image uploaded = suspicious (bot account)
- ❌ Image uploaded within 30 seconds of registration = pre-prepared (stolen image)
- ✅ Image uploaded 2-10 minutes after registration = likely legitimate

**Use Case**: Cross-reference with reverse image search (Google Images, TinEye) to detect:
- Stock photos from Shutterstock, Getty Images
- Images stolen from other profiles
- AI-generated faces

---

### 5. Account Metadata (Additional Context)
**Fields**:
- `first_login_timestamp` - Detect registration IP ≠ login IP (geolocation fraud)
- `profile_completion_timestamp` - Bots complete profiles instantly
- `profile_image_url` - Enable reverse image search for fake profiles
- `device_fingerprint` or `user_agent` - Already have; confirm availability via API

**Reason**: Cross-reference behavior patterns across multiple dimensions

---

## Priority 2: Real-Time Access (Webhooks/Events)

### Account Creation Event Hook
**Trigger**: When new account is created  
**Payload Required**:
```json
{
  "event": "account.created",
  "timestamp": "2025-01-25T14:30:00Z",
  "data": {
    "duid": "384046981",
    "email": "user@example.com",
    "ip": "192.168.1.1",
    "campaign": "campaign_name",
    "affiliate_code": "AFF123",
    "registration_timestamp": "2025-01-25T14:30:00Z"
  }
}
```

**Use Case**: Real-time fraud scoring within 4-hour window (before first payout)

---

### Email Validation Event Hook
**Trigger**: When user validates their email  
**Payload Required**:
```json
{
  "event": "email.validated",
  "timestamp": "2025-01-25T14:30:15Z",
  "data": {
    "duid": "384046981",
    "email": "user@example.com",
    "validation_method": "click_link" | "enter_code",
    "validation_timestamp": "2025-01-25T14:30:15Z"
  }
}
```

**Use Case**: Instant bot detection (validation < 60 seconds)

---

## Priority 3: Scheduled Data Export (Alternative if No API)

If real-time API access is not feasible, we can work with **scheduled automated exports**:

### Option A: Scheduled CSV/JSON Exports
**Frequency**: Every 4 hours (or configurable)  
**Format**: CSV or JSON  
**Delivery**: SFTP, S3 bucket, or webhook POST  
**Tables**: 
- `accounts` (with registration timestamp, email validation timestamp)
- `transactions` (existing data, ensure timestamps included)
- `email_validations` (validation events with timestamps)

**Minimum Viable**: Daily exports would still save 90 min/week

### Option B: Database Read-Only Access
**Type**: MySQL/PostgreSQL read replica  
**Access**: VPN + IP whitelist  
**Tables**: Same as Option A  
**Security**: Read-only user, limited to fraud-related tables

---

## Specific Endpoints Requested (REST API)

### 1. GET `/api/accounts/{duid}`
**Response**:
```json
{
  "duid": "384046981",
  "email": "user@example.com",
  "registration_timestamp": "2025-01-25T14:30:00Z",
  "email_validated": true,
  "email_validation_timestamp": "2025-01-25T14:30:15Z",
  "first_login_timestamp": "2025-01-25T14:35:00Z",
  "profile_completed": true,
  "affiliate_code": "AFF123",
  "campaign": "campaign_name",
  "ip_address": "192.168.1.1",
  "user_agent": "Mozilla/5.0...",
  "geo_country": "US",
  "payment_method_fingerprint": "card_abc123xyz",
  "profile_image_uploaded": true,
  "image_upload_timestamp": "2025-01-25T14:32:00Z"
}
```

### 2. GET `/api/accounts/{duid}/billing-relationships`
**Response**: Show accounts using same payment method
```json
{
  "duid": "384046981",
  "payment_method_fingerprint": "card_abc123xyz",
  "relationship_type": "used_by",  // Only "used_by", NOT "possible_match"
  "shared_accounts": [
    {
      "duid": "384047001",
      "email": "user2@example.com",
      "registration_timestamp": "2025-01-25T15:00:00Z",
      "affiliate_code": "AFF123"
    },
    {
      "duid": "384047125",
      "email": "user3@example.com",
      "registration_timestamp": "2025-01-25T16:00:00Z",
      "affiliate_code": "AFF456"
    }
  ],
  "shared_card_count": 3,
  "fraud_risk": "high"  // If count > 3
}
```

**Important**: Only return **confirmed "used_by" relationships** (exact card match), NOT fuzzy "possible_match" results.

### 3. GET `/api/accounts/{duid}/admin-events`
**Response**: Profile activity events (image uploads, edits)
```json
{
  "duid": "384046981",
  "events": [
    {
      "event_type": "profile_image_upload",
      "timestamp": "2025-01-25T14:32:00Z",
      "ip_address": "192.168.1.1",
      "image_url": "https://cdn.example.com/profiles/384046981.jpg"  // For reverse image search
    },
    {
      "event_type": "profile_edit",
      "timestamp": "2025-01-25T14:35:00Z",
      "fields_changed": ["bio", "location"]
    }
  ]
}
```

### 4. GET `/api/accounts?created_after={timestamp}`
**Query Params**:
- `created_after`: ISO 8601 timestamp
- `created_before`: ISO 8601 timestamp (optional)
- `limit`: 1000 (default)
- `offset`: For pagination

**Use Case**: Batch fetch new accounts every 4 hours

### 3. GET `/api/email-validations?duid={duid}`
**Response**:
```json
[
  {
    "duid": "384046981",
    "email": "user@example.com",
    "validated_at": "2025-01-25T14:30:15Z",
    "method": "click_link",
    "ip_address": "192.168.1.1"
  }
]
```

---

## Data Security & Privacy

**Our Commitments**:
- ✅ Store data locally (not cloud) in encrypted SQLite database
- ✅ No third-party data sharing
- ✅ Access limited to fraud detection team only
- ✅ Comply with GDPR/privacy regulations (data retention policies)
- ✅ Secure API key storage (environment variables, not code)
- ✅ HTTPS-only communication
- ✅ IP whitelist for API access (if required)

**Data Retention**: 
- Raw data: 90 days
- Aggregated/anonymized metrics: 1 year

---

## Technical Implementation Plan

**Phase 1: Timestamps (Immediate)**
1. Add `registration_timestamp` and `email_validation_timestamp` to account export
2. Update fraud detection to calculate validation time
3. Deploy new "Email Validation Timing" rule (60-second threshold)
4. **Timeline**: 2 weeks (1 week dev, 1 week testing)

**Phase 2: Real-Time Webhooks (3-6 months)**
1. Set up webhook receiver endpoint (our side)
2. Configure account creation & email validation webhooks (your side)
3. Implement real-time fraud scoring
4. Deploy alert system (Slack/email notifications)
5. **Timeline**: 1-2 months after webhook access granted

**Phase 3: Full Automation (6-12 months)**
1. Scheduled exports or database access
2. Automated daily analysis
3. Integration with Asana (auto-create tasks)
4. Dashboards in Metabase/Kibana
5. **Timeline**: Ongoing optimization

---

## Fallback Options (If Full API Not Available)

### Minimum Viable Request
If full API access is not feasible, we can start with:

1. **Just add 2 fields to existing CSV exports**:
   - `account_creation_timestamp`
   - `email_validation_timestamp`
   - This alone enables our #1 fraud detection rule!

2. **One-time database schema documentation**:
   - Table names and field definitions
   - Helps us write better import scripts

3. **Monthly data dump** (instead of API):
   - Bulk export of all accounts from last month
   - Include timestamps
   - Better than nothing!

---

## Cost-Benefit Analysis

**Development Time (Your Team)**:
- Add timestamps to exports: **4 hours**
- Build REST API endpoints: **2-3 weeks**
- Set up webhooks: **1-2 weeks**
- Database read access: **1 week**

**Value Delivered**:
- **Fraud prevented**: $50K-$100K+ annually (estimated)
- **Time saved**: 90 min/week manual exports → 0
- **Detection speed**: 24+ hours → <4 hours
- **False positive reduction**: Better data = better accuracy
- **Automated reporting**: Weekly metrics for stakeholders

**ROI**: Even at 4 hours of dev time for timestamps, the ROI is **500x+** annually

---

## Success Metrics (How We'll Measure Impact)

After API access is granted, we'll track:

1. **Fraud Detection Rate**: % of fraud caught before first payout
2. **Time to Detection**: Average hours from registration to flag
3. **False Positive Rate**: % of flagged accounts that are legitimate
4. **Manual Work Reduction**: Hours saved per week
5. **$ Fraud Prevented**: Confirmed fraud × payout amount

**Reporting**: Quarterly reports to stakeholders (Finance, Marketing, Operations)

---

## Next Steps

1. **Review this request** with your team
2. **Prioritize which option** works best (API, webhooks, exports, DB access)
3. **Schedule a 30-min meeting** to discuss technical implementation
4. **Timeline estimate** from your side for development
5. **API documentation** (if available) for our integration planning

---

## Contact Information

**Primary Contact**: [Your Name]  
**Email**: [Your Email]  
**Slack**: [Your Slack Handle]  
**Team**: Fraud Detection / Risk Management  

**Available for**:
- Technical discussion (data formats, security requirements)
- User acceptance testing (UAT) after implementation
- Ongoing feedback and optimization

---

## Appendix: Current System Capabilities

**What We Already Have**:
- ✅ Email pattern detection (dots, digits, scrambled usernames)
- ✅ Domain concentration analysis
- ✅ Name-number pattern detection
- ✅ Billing name/gender mismatch detection
- ✅ IP clustering and geolocation analysis
- ✅ Device fingerprinting (user agent)
- ✅ Campaign/affiliate analysis
- ✅ Statistical outlier detection (amounts, timing)
- ✅ Web dashboard with 8+ visualization charts
- ✅ Web dashboard and REST APIs
- ✅ PDF report generation
- ✅ Business metrics & ROI tracking

**What We're Missing** (This Request):
- ❌ Account registration timestamps
- ❌ Email validation timestamps  
- ❌ Real-time event hooks
- ❌ Automated data access (currently manual CSV exports)

**With API Access**: Our detection accuracy could improve by **30-50%** and catch fraud **20x faster**.

---

**Thank you for considering this request!**

We're excited to collaborate and build a more robust fraud detection system that benefits the entire organization.

---

*Last Updated: January 25, 2026*
