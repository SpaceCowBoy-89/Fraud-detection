# Fraud flags reference (exportable)

Stakeholder-ready list of detection flags, descriptions, and risk points.

## Dashboard

**Settings → Configuration & Settings → Flag reference (for Fraud / Ops)**

- [CSV](/api/export/flag-reference?format=csv) — Excel; columns include trigger, explanation, investigation, and **active score points**  
- [Markdown](/api/export/flag-reference?format=md) — **full narrative guide** (methodology, score table, per-flag deep dive)  
- [JSON](/api/export/flag-reference?format=json) — includes `score_tiers_resolved` and `active_config`  

Exports use **current `config.json` risk scores and thresholds** when the app is running.

## Command line

From the project root:

```bash
python3 scripts/fraud_flags_reference.py --format csv --use-config -o fraud_flags_reference.csv
python3 scripts/fraud_flags_reference.py --format json --use-config -o fraud_flags_reference.json
python3 scripts/fraud_flags_reference.py --format md -o fraud_flags_reference.md
```

## Source of truth

| File | Purpose |
|------|---------|
| [`fraud_flags_catalog.json`](fraud_flags_catalog.json) | Flag list, categories, phases |
| [`fraud_flags_extended.json`](fraud_flags_extended.json) | In-depth trigger / explanation / investigation / score tiers |

Update both when adding flags, then re-export for Fraud/Ops.

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/export/flag-reference?format=csv\|json\|md` | File download |
| `GET /api/flags/reference` | Same catalog as JSON (no attachment) |
