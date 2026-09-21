# Critical Data Fields for API Access - Quick Reference

## 📋 Priority Order (Request These First)

### 🔥 Priority 1: Timestamps (Highest Impact)
1. **Registration Timestamp** - `account_creation_timestamp` or `registration_datetime`
2. **Email Validation Timestamp** - `email_validation_timestamp` or `pov_verified_time`

**Why**: Email validated within 60 seconds = 95% fraud rate  
**Impact**: Could prevent 40% of fraud losses ($50K+ annually)  
**Dev Effort**: ~4 hours

---

### 🎯 Priority 2: Billing Relationships (Fraud Rings)
3. **Shared Credit Card Data** - `credit_card_fingerprint` + `used_by_accounts`

**Important**: 
- ✅ Only include **"Used By"** (confirmed same card)
- ❌ Exclude **"Possible Match"** (fuzzy matching - too many false positives)
- ✅ Use **hashed/tokenized** card fingerprint (not raw card numbers)
- ✅ Filter out major issuers: Bank of America, Chase, Capital One, Citi

**Why**: Same card used by 5+ accounts = organized fraud ring  
**Impact**: Catch networks of 10-50 fraudulent accounts  
**Dev Effort**: ~1-2 days (depends on billing system access)

---

### 📸 Priority 3: Admin Event Logs (Profile Behavior)
4. **Profile Image Upload Events** - `profile_image_upload_timestamp` + `has_uploaded_image`

**Why**: 
- No image = bot account
- Image uploaded within 30 seconds = stolen/stock image
- Normal users take 2-10 minutes

**Impact**: Enable reverse image search for fake profiles  
**Dev Effort**: ~1 day (access to admin event logs)

---

## 📊 Example Data Formats

### Timestamps (CSV Export)
```csv
duid,email,registration_timestamp,email_validation_timestamp,payout_amount,campaign
384046981,user@example.com,2025-01-25 14:30:00,2025-01-25 14:30:15,50.00,campaign_x
384047001,bot@example.com,2025-01-25 14:35:00,2025-01-25 14:35:05,50.00,campaign_y
                                                          ↑ 5 seconds = BOT
```

### Billing Relationships (API Response)
```json
{
  "duid": "384046981",
  "payment_method_fingerprint": "card_abc123xyz",
  "relationship_type": "used_by",
  "shared_accounts": [
    {"duid": "384047001", "email": "user2@example.com"},
    {"duid": "384047125", "email": "user3@example.com"},
    {"duid": "384048002", "email": "user4@example.com"}
  ],
  "shared_card_count": 4,
  "fraud_risk": "high"
}
```

### Admin Events (API Response)
```json
{
  "duid": "384046981",
  "profile_image_uploaded": true,
  "image_upload_timestamp": "2025-01-25T14:30:25Z",
  "upload_time_after_registration": 25,
  "image_url": "https://cdn.example.com/profiles/384046981.jpg"
}
```

---

## 🎯 Fraud Detection Rules Enabled by These Fields

### Rule 1: Email Validation Timing (60-Second Rule)
**Formula**: `email_validation_timestamp - registration_timestamp < 60 seconds`  
**Risk Score**: +40 points  
**Accuracy**: 95% fraud detection rate  
**Enabled by**: Timestamps (Priority 1)

### Rule 2: Shared Credit Card (Fraud Ring Detection)
**Formula**: `shared_card_count >= 5 accounts`  
**Risk Score**: +50 points  
**Pattern**: Organized fraud networks  
**Enabled by**: Billing relationships (Priority 2)

### Rule 3: Profile Image Behavior
**Patterns**:
- No image uploaded: +20 points (bot account)
- Image uploaded < 30 seconds: +35 points (pre-prepared/stolen)
- Image uploaded 2-10 minutes: 0 points (normal)

**Enabled by**: Admin event logs (Priority 3)

### Rule 4: Combined Multi-Account + Fast Validation
**Formula**: `shared_card_count >= 3 AND validation_time < 60 seconds`  
**Risk Score**: +80 points (almost certain fraud)  
**Pattern**: Bot network using same payment method  
**Enabled by**: Priorities 1 + 2 combined

---

## 🔐 Security Requirements

### For Billing Data
- ✅ **Hash/tokenize card numbers**: Use format like `card_abc123xyz`
- ✅ **No PCI data**: Don't send last 4 digits, expiry, CVV
- ✅ **Fingerprint only**: One-way hash sufficient for matching
- ✅ **Filter major issuers**: Exclude Bank of America, Chase, Capital One, Citi

### For Image URLs
- ✅ **CDN URLs only**: Direct links to images (for reverse search)
- ✅ **No private data**: Images should already be public/profile images
- ✅ **Expiring links OK**: We'll download immediately for analysis

### For All Data
- ✅ **HTTPS only**: Encrypted transport
- ✅ **API key auth**: Secure authentication
- ✅ **IP whitelist**: Lock to our IP addresses
- ✅ **90-day retention**: We delete raw data after 90 days

---

## 📈 Expected Impact

### Before API Access
- Manual CSV exports: 90 min/week
- Detection time: 24+ hours
- Fraud patterns: 8 automated rules
- Missing critical data: Timing, billing relationships, profile behavior

### After API Access (All 3 Priorities)
- Manual CSV exports: 0 min (automated)
- Detection time: <4 hours (real-time with webhooks)
- Fraud patterns: 12+ automated rules (50% more)
- Fraud prevention: +$50K-$100K annually

### Just Timestamps Alone (Priority 1)
- Fraud prevention: +$50K annually
- New rules: 3 (validation timing + combined patterns)
- Dev effort: 4 hours
- **ROI: 500x+**

---

## 💬 How to Ask for This Data

### Email Template (30 Seconds)
```
Subject: Quick Request - Add Critical Fraud Detection Fields

Hi [Developer],

I need 3 data points to dramatically improve our fraud detection:

1. Registration timestamp (when account created)
2. Email validation timestamp (when they verified email)
3. Billing: "Used By" data showing shared credit cards
   (Only confirmed matches, not "Possible Match" fuzzy data)

Bonus: Admin event logs for profile image uploads

Why: Email validated within 60 seconds = 95% fraud. Same card 
used by 5+ accounts = fraud ring. This could prevent $50K+ fraud 
annually.

Can we schedule 15 min to discuss?

Thanks!
```

### In a Meeting
**Talking Points**:
1. Show the 60-second validation pattern (concrete, measurable)
2. Explain fraud rings using same credit card (5-50 accounts)
3. Demonstrate bot detection via image upload timing
4. Emphasize: Just need hashed data, not raw card numbers
5. Start small: Even just timestamps in CSV is 80% of value

---

## 📚 Full Documentation

**Comprehensive API Request**: `/docs/API_ACCESS_REQUEST.md`  
**Quick Email Template**: `/docs/API_REQUEST_EMAIL.md`  
**Meeting Agenda**: `/docs/API_MEETING_AGENDA.md`

---

## ✅ Checklist for Developer

When you talk to the developer, confirm:

### Timestamps
- [ ] Where is `registration_timestamp` stored? (table/column)
- [ ] Where is `email_validation_timestamp` stored?
- [ ] What datetime format? (ISO 8601, Unix timestamp, etc.)
- [ ] Can add to existing CSV exports?
- [ ] Timeline estimate?

### Billing Relationships
- [ ] How is "Used By" data accessed? (API/database/report)
- [ ] Already hashed/tokenized or need to implement?
- [ ] Can filter by "Used By" only (exclude "Possible Match")?
- [ ] How to exclude major issuers?
- [ ] Timeline estimate?

### Admin Event Logs
- [ ] Where are image upload events stored?
- [ ] Can access via API or need database query?
- [ ] Includes timestamp + image URL?
- [ ] Any privacy/security concerns?
- [ ] Timeline estimate?

---

**Last Updated**: January 25, 2026

**Quick Win**: Just getting timestamps (Priority 1) would be a **massive improvement** - start there!
