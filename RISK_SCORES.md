# Fraud Detection Risk Scores

This document lists all fraud detection flags and their associated risk scores.

## Risk Levels

| Level | Score Range | Action |
|-------|-------------|--------|
| **HIGH RISK** | 50+ | Immediate investigation required |
| **MEDIUM RISK** | 25-49 | Review recommended |
| **LOW RISK** | 0-24 | Normal monitoring |

---

## Email Pattern Flags

| Flag | Points | Description |
|------|--------|-------------|
| `EXCESSIVE_DOTS` | 20 | More than 3 dots in email username |
| `DIGIT_SUFFIX` | 15 | Email ends with 4-5 consecutive digits |
| `SCRAMBLED_PATTERN` | 35 | Email appears randomly generated (low vowel ratio, consonant clusters) |
| `NAME_NUMBER_PATTERN` | 40 | Pattern like `firstname12lastname4567@domain` |
| `WRITTEN_NUMBER_PATTERN` | 15 | Contains written numbers (one, two, three, etc.) |
| `REPEATED_WORD_PATTERN` | 25 | Contains words that appear in 4+ emails in dataset |
| `SUSPICIOUS_NAME` | 30 | Contains known fraud-associated names |
| `DOMAIN_CONCENTRATION` | 20 | High concentration (>90%) from same non-major domain |
| `THEME_CLUSTER_*` | 15 | Email matches theme cluster (real_estate, construction, crypto, finance) |

---

## POV (Proof of Verification) Timing Flags

| Flag | Points | Description |
|------|--------|-------------|
| `POV_INSTANT_VALIDATION_20S` | 50 | Email verified within 20 seconds (likely automated) |
| `POV_INSTANT_VALIDATION_40S` | 40 | Email verified within 40 seconds |
| `POV_FAST_VALIDATION_60S` | 30 | Email verified within 60 seconds |

---

## Device & Network Flags

| Flag | Points | Description |
|------|--------|-------------|
| `DESKTOP_DEVICE_SUSPICIOUS` | 20 | Windows 10 desktop (common in fraud farms) |
| `DESKTOP_DEVICE_SUSPICIOUS` | 10 | Other desktop OS (Mac, Linux, older Windows) |
| `IP_VELOCITY_HIGH` | 30 | IP has 10+ signups/hour (fraud ring indicator) |
| `IP_VELOCITY_MEDIUM` | 5 | IP has 5+ signups/hour |

---

## Geographic Clustering Flags

| Flag | Points | Description |
|------|--------|-------------|
| `SAME_US_STATE_CLUSTER` | 25 | 3+ accounts from same US state |
| `SAME_US_CITY_STATE_CLUSTER` | 30 | 3+ accounts from same US city and state |
| `SAME_INTL_COUNTRY_CITY_CLUSTER` | 30 | 3+ accounts from same international city |

---

## Score Calculation Notes

1. **Score Cap**: Maximum risk score is capped at 100
2. **Cumulative**: Multiple flags add up (an account can have multiple indicators)
3. **Dynamic Patterns**: Some patterns (like `REPEATED_WORD_PATTERN`) are detected dynamically based on the current dataset
4. **Whitelisting**: Major email providers (gmail.com, yahoo.com, etc.) are excluded from domain concentration analysis

---

## Modifying Scores

All risk scores are now **config-driven**. Edit `config.json` to adjust:

```json
{
  "risk_scores": {
    "excessive_dots": 20,
    "digit_suffix": 15,
    "scrambled_pattern": 35,
    "name_number_pattern": 40,
    "written_number_pattern": 15,
    "repeated_word_pattern": 25,
    "suspicious_name": 30,
    "domain_concentration": 20,
    "pov_instant_20s": 50,
    "pov_instant_40s": 40,
    "pov_fast_60s": 30,
    "ip_velocity_high": 30,
    "ip_velocity_medium": 5,
    "desktop_windows_10": 20,
    "desktop_other": 10,
    "us_state_cluster": 25,
    "us_city_state_cluster": 30,
    "intl_country_city_cluster": 30,
    "theme_cluster": 15
  }
}
```

Changes take effect on next detection run without code changes.

---

## Suspicious Names List

Currently hardcoded in `email_fraud_detector.py`:
- fatima
- muhammed

To add more, edit the `self.suspicious_names` list in the `__init__` method.

---

## Theme Keywords

Emails containing these keywords are flagged for theme clustering:

| Theme | Keywords |
|-------|----------|
| real_estate | realty, realtor, property, homes, estate, housing |
| construction | construction, builder, contractor, building, concrete |
| crypto | crypto, bitcoin, blockchain, btc, eth |
| finance | finance, invest, capital, trading, forex |
