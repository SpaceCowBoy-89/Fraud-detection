# Billing Gender Mismatch Detection

## Overview

The `BILLING_GENDER_MISMATCH` detection rule identifies potential fraud by comparing the predicted gender of a billing name (first_name) against the declared gender (user1 field). This is a strong fraud indicator when someone uses a stolen payment method.

## How It Works

1. **Extracts billing first name** from paid records
2. **Predicts gender** using the `gender-guesser` library
3. **Compares** predicted gender against declared gender (user1 field)
4. **Flags mismatches** with high confidence
5. **Adds risk points** (configurable, default: +35)

## Examples

### Fraud Cases
- Billing name: **Patricia**, Declared gender: **man** ❌
- Billing name: **John**, Declared gender: **woman** ❌
- Billing name: **Michael**, Declared gender: **female** ❌

### Legitimate Cases
- Billing name: **Sarah**, Declared gender: **woman** ✓
- Billing name: **David**, Declared gender: **man** ✓
- Billing name: **Alex**, Declared gender: **any** ✓ (androgynous - skipped)

## Configuration

### Risk Score (config.json)
```json
{
  "risk_scores": {
    "billing_gender_mismatch": 35
  }
}
```

### Supported Gender Values
The detector normalizes various inputs:

**Male**: `man`, `male`, `m`, `Man`, `MALE`
**Female**: `woman`, `female`, `f`, `Woman`, `FEMALE`

## Implementation Details

### Requirements
```bash
pip install gender-guesser
```

### Only Runs on Paid Records
- Free records don't have billing names (first_name)
- Check requires both `first_name` and `user1` fields
- Automatically skips records missing either field

### Confidence Filtering
The detector only flags high-confidence mismatches:
- **High confidence**: Names strongly associated with one gender (e.g., Patricia, John)
- **Medium confidence**: Names mostly associated with one gender
- **Skipped**: Androgynous names (e.g., Alex, Jordan), unknown names, ambiguous cases

### Gender-Guesser Library
- Uses international name database
- Returns: `male`, `female`, `mostly_male`, `mostly_female`, `andy` (androgynous), `unknown`
- Trained on over 40,000 names across 54 countries

## Output

When a mismatch is detected, the fraud result includes:

```python
{
  "risk_score": 35,  # (or higher if other flags present)
  "flags": ["BILLING_GENDER_MISMATCH"],
  "details": {
    "gender_mismatch": {
      "billing_name": "Patricia",
      "predicted_gender": "female",
      "declared_gender": "male",
      "confidence": "high"
    }
  }
}
```

## False Positive Scenarios

1. **Unisex names**: Alex, Jordan, Riley - automatically skipped
2. **Cultural names**: Names from different cultures may predict differently
3. **Nicknames**: "Pat" could be Patricia or Patrick
4. **Typos**: Misspelled names in billing info
5. **Shared accounts**: Legitimate family member using partner's card

## Integration

### In the dashboard
Run fraud analysis from the UI — the check runs automatically on paid records:
```bash
python run.py
# Overview / Analysis → Run analysis on paid data
```

### In Dashboard
- Appears in flag dropdown filter
- Shows in account detail modal
- Included in false positive analysis

### In Code
```python
from scripts.email_fraud_detector import EmailFraudDetector

detector = EmailFraudDetector(config)

result = detector.analyze_email(
    email='test@example.com',
    first_name='Patricia',  # Billing name
    user1='man'             # Declared gender
)

if 'BILLING_GENDER_MISMATCH' in result['flags']:
    print(f"Mismatch detected: {result['details']['gender_mismatch']}")
```

## Testing

Run tests:
```bash
pytest tests/test_gender_mismatch.py -v
```

Manual test:
```python
from scripts.email_fraud_detector import EmailFraudDetector

detector = EmailFraudDetector()
result = detector.check_gender_mismatch('Patricia', 'man')
print(result)  # {'mismatch': True, 'predicted_gender': 'female', ...}
```

## Performance

- **Speed**: ~0.001s per name lookup (library uses cached lookups)
- **Memory**: Negligible (name database loaded once)
- **Accuracy**: High for common Western names, variable for international names

## Future Improvements

1. **Cultural context**: Add country parameter for better international name detection
2. **Nickname mapping**: Expand "Pat" → ["Patricia", "Patrick"] mappings
3. **Historical analysis**: Track false positive rate by name
4. **Confidence threshold**: Make confidence level configurable
5. **Alternative providers**: Support additional gender detection services

## References

- gender-guesser library: https://pypi.org/project/gender-guesser/
- Based on genderize.io research
- Name database: https://github.com/lead-ratings/gender-guesser
