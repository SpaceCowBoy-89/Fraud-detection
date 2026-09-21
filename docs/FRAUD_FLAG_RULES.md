# Fraud detection flags — reference guide

_Exported: 2026-09-21T18:04:46Z_

## Risk levels (account action bands)

| Level | Score range | Typical action |
|-------|-------------|----------------|
| **High** | 50+ | Immediate investigation |
| **Medium** | 25–49 | Review recommended |
| **Low** | 0–24 | Routine monitoring |

Account **risk_score** sums flag points from all applicable rules, **capped at 100**.

## How scoring works

Each account receives a risk_score from 0–100. Points from multiple flags add together. The total is capped at 100. Risk bands: Low 0–24, Medium 25–49, High 50+ (thresholds configurable in config.json).

1. Per-account email, device, IP velocity, and geo-cluster rules run on each lead/registration row.
2. Affiliate batch rules (sequential email, woman concentration, domain concentration) run on the same dataset and flag only matching accounts.
3. Admin enrichment adds payment, GeoIP, email-validation timing, and content-review flags for enriched (typically paid) accounts.
4. Post-enrichment batch rules (e.g. Discover concentration per affiliate) apply after enrichment completes.

**Intentionally not scored:**
- Raw registration IP ≠ login IP (users switch Wi‑Fi/mobile) — only geo-based mismatches are scored.
- Apple Private Relay and phone-registration placeholder domains skip local-part email pattern rules.

## Admin — IP / GeoIP

### `ip_country_mismatch`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Registration IP country ≠ login IP country.

**When it triggers:** GeoIP country of registration IP ≠ GeoIP country of login IP.

**Why it matters:** Cross-country movement between signup and login is suspicious on dating products when paired with other signals. Different from raw IP string mismatch.

**Scores (active):** 35 pts — Reg country ≠ login country [ip_different_country]

**Investigation tips:** Confirm countries in flag text. High-risk login country adds separate points.

**Notes:** Stored as: ip_country_mismatch_{CC}→{CC}(+pts)

---

### `ip_state_mismatch`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Same country but registration state ≠ login state.

**When it triggers:** Same country but US state (or region) differs between registration and login IP.

**Why it matters:** Cross-state moves happen legitimately but add risk when combined with automation signals.

**Scores (active):** 15 pts — Same country, different state [ip_different_state]

**Investigation tips:** Not scored for different cities within same state.

**Notes:** Stored as: ip_state_mismatch_{ST}→{ST}(+pts)

---

### `login_high_risk_country`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Login IP in configured high-risk country list.

**When it triggers:** Login IP country in config high_risk_countries (default: NG, GH, CI, CM, PH, RO, MD, ID).

**Why it matters:** Login from geographies over-represented in dating fraud ops.

**Scores (active):** 30 pts — Login country in list [login_high_risk_country]

**Investigation tips:** Validate against declared geo in CSV; list is configurable.

**Notes:** Stored as: login_high_risk_country_{CC}(+pts)

---

### `geo_login_mismatch`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Login IP country ≠ geo_country from leads CSV.

**When it triggers:** Login IP country ≠ geo_country from affiliate/leads CSV.

**Why it matters:** Cross-source inconsistency—lead data says one country, login IP another.

**Scores (active):** 25 pts — Login country ≠ CSV geo_country [geo_login_country_mismatch]

**Investigation tips:** Data quality vs fraud—check if CSV geo is stale or VPN-related.

**Notes:** Stored as: geo_login_mismatch_{CC}→{CC}(+pts)

---

### `registration_ip_datacenter`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Registration IP resolves to datacenter/cloud hosting ASN.

**When it triggers:** Registration IP ASN classified as datacenter/cloud (AWS, GCP, Azure, etc.).

**Why it matters:** Consumer dating signups rarely originate from cloud host IPs.

**Scores (active):** 25 pts — Registration IP datacenter [registration_ip_datacenter]

**Investigation tips:** ASN name appears in flag. Pair with email automation flags.

**Notes:** Stored as: registration_ip_datacenter_{org}(+pts)

---

### `login_ip_datacenter`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Login IP resolves to datacenter/cloud hosting ASN.

**When it triggers:** Login IP ASN is datacenter/cloud.

**Why it matters:** Bots and scripted logins often use hosted infrastructure.

**Scores (active):** 25 pts — Login IP datacenter [login_ip_datacenter]

**Investigation tips:** Compare to registration IP type.

**Notes:** Stored as: login_ip_datacenter_{org}(+pts)

---

### `registration_ip_vpn`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Registration IP on known VPN/proxy ASN.

**When it triggers:** Registration IP ASN matches known VPN/proxy providers.

**Why it matters:** Anonymized registration path—elevated risk on affiliate traffic.

**Scores (active):** 20 pts — Registration IP VPN/proxy ASN [registration_ip_vpn]

**Investigation tips:** VPN at registration + fast validation is high priority.

**Notes:** Stored as: registration_ip_vpn_{org}(+pts)

---

### `login_ip_vpn`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Login IP on known VPN/proxy ASN.

**When it triggers:** Login IP on VPN/proxy ASN.

**Why it matters:** Common for fraud operators masking location.

**Scores (active):** 20 pts — Login IP VPN/proxy ASN [login_ip_vpn]

**Investigation tips:** Compare with geo_login_mismatch.

**Notes:** Stored as: login_ip_vpn_{org}(+pts)

---

## Admin — email validation timing

### `email_validated`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Email validated within 60s (+50) or 61–120s (+30) of account creation (Admin API).

**When it triggers:** Admin API: seconds from account creation to email validation ≤ 60 or ≤ 120.

**Why it matters:** Strongest automated signal when platform timestamps are available—mirrors manual POV analysis at scale.

**Scores (active):** 50 pts — Validation ≤ 60s after registration [email_validated_60s] | 30 pts — Validation 61–120s [email_validated_120s]

**Investigation tips:** Prioritize ≤60s accounts for affiliate termination discussions. Flag stored as email_validated_{N}s(+points).

**Notes:** Also uses email_validated_120s config for 61–120 second window. | Stored as: email_validated_{N}s(+pts)

---

## Admin — payment / card

### `shared_card`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Same non-excluded card linked to 3+ other accounts (35 pts) or 5+ (50 pts). Major issuers excluded.

**When it triggers:** Confirmed shared card (Used By, not fuzzy match) links account to 3+ or 5+ other DUIDs; major issuers excluded.

**Why it matters:** Same payment credential across many accounts indicates fraud ring or stolen card testing.

**Scores (active):** 35 pts — 3–4 other accounts on same card [shared_card_3plus] | 50 pts — 5+ other accounts [shared_card_5plus]

**Investigation tips:** Use Admin shared cards view; 5+ is ring-level priority. QA cards/DUIDs can be whitelisted in config.

**Notes:** 5+ accounts uses shared_card_5plus config. | Stored as: shared_card_{N}_accounts(+pts)

---

### `amex_card`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** American Express on file (rare baseline on dating sites).

**When it triggers:** Any Amex cardType on account payment methods.

**Why it matters:** Amex has near-zero baseline on typical dating traffic—any appearance is anomalous.

**Scores (active):** 30 pts — Amex present [amex_card]

**Investigation tips:** Verify charge outcomes; check billing gender mismatch.

**Notes:** Stored as: amex_card(+pts)

---

### `business_card`

**Phase:** admin_enrichment — After Admin API + GeoIP enrichment (typically paid/enriched accounts).

**Summary:** Business/corporate card description on a dating site account.

**When it triggers:** cardDescription contains business/corporate/commercial/company/enterprise keywords.

**Why it matters:** Business cards are inherently unusual for consumer dating purchases.

**Scores (active):** 40 pts — Business card description [business_card]

**Investigation tips:** Confirm description text in Admin; no issuer exclusions.

**Notes:** Stored as: business_card(+pts)

---

### `discover_concentration`

**Phase:** post_enrichment — Batch rule after enrichment completes (e.g. Discover concentration).

**Summary:** Affiliate enriched accounts: Discover cards exceed threshold (default >10%, min 10 accounts); flags Discover-card accounts only.

**When it triggers:** Post-enrichment: affiliate has >10% Discover cards among enriched accounts (default), minimum 10 enriched accounts.

**Why it matters:** Discover baseline ~2% site-wide; affiliate-level spikes suggest bad traffic mix.

**Scores (active):** 20 pts — Discover account from hot affiliate [discover_concentration]

**Investigation tips:** Only Discover-card accounts flagged. Affiliate negotiation / cap traffic.

**Notes:** Stored as: discover_concentration_{pct}pct_at_{affiliate}(+pts)

---

## Affiliate batch

### `SEQUENTIAL_EMAIL`

**Phase:** affiliate_batch — Second pass on the analysis batch; only matching accounts are flagged.

**Summary:** Same affiliate: same text stem + domain with 4+ distinct numeric suffixes on local part.

**When it triggers:** Same affiliate: same letter stem (≥4 chars) + same domain, with 4+ distinct numeric suffixes on local part.

**Why it matters:** Detects factory-style email generation (e.g. maucheesee71@, maucheesee76@) without requiring consecutive numbers.

**Scores (active):** 30 pts — Account in detected cluster [sequential_email]

**Investigation tips:** Affiliate-level abuse indicator—review entire affiliate cohort sharing the stem.

---

### `WOMAN_CONCENTRATION`

**Phase:** affiliate_batch — Second pass on the analysis batch; only matching accounts are flagged.

**Summary:** Affiliate has abnormally high WOMAN registration share (default ≥15%); flags WOMAN accounts from that affiliate.

**When it triggers:** Affiliate WOMAN share ≥ ~15% (configurable in build_gender_concentration_map) with sufficient sample; baseline ~0.9%.

**Why it matters:** Flags only WOMAN registrations from affiliates with abnormal gender mix—often mislabeled or scripted female profiles.

**Scores (active):** 25 pts — WOMAN account from concentrated affiliate [woman_concentration]

**Investigation tips:** Affiliate quality conversation; compare to campaign and geo. Only flagged gender rows receive points.

---

### `AFFILIATE_DOMAIN_CONCENTRATION`

**Phase:** affiliate_batch — Second pass on the analysis batch; only matching accounts are flagged.

**Summary:** Non-excluded domain (default: not gmail.com) is ≥5% of affiliate emails with ≥20 registrations; flags accounts on that domain only.

**When it triggers:** Affiliate has ≥20 emails in batch; non-excluded domain (default: not gmail.com) is ≥5% of that affiliate's domains.

**Why it matters:** Fraud sources funnel traffic through disposable or niche domains. Gmail is excluded by default because it dominates legitimate traffic.

**Scores (active):** 20 pts — Email domain matches concentrated pair (affiliate, domain) [affiliate_domain_concentration]

**Investigation tips:** Inspect domain WHOIS/reputation; only accounts on the concentrated domain are flagged—not all affiliate traffic.

---

## Data quality

### `DATA_QUALITY_MISSING_EMAIL`

**Phase:** data_quality — Data issue, not a fraud pattern.

**Summary:** Missing email on record; fraud analysis skipped for row.

**When it triggers:** Email field empty or missing on input row.

**Why it matters:** Row skipped for pattern analysis; indicates export or pipeline data gap.

**Scores (active):** 0 pts — No email

**Investigation tips:** Fix upstream data—not a fraud finding.

---

## Email & identity

### `EXCESSIVE_DOTS`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** More than 3 dots in the email local part.

**When it triggers:** More than 3 period characters in the email local part (before @).

**Why it matters:** Fraud farms often insert extra dots in Gmail-style addresses to create many unique-looking emails from one inbox or to evade naive duplicate checks. Legitimate users rarely use more than three dots in a username.

**Scores (active):** 20 pts — Always when rule matches [excessive_dots]

**Investigation tips:** Compare with affiliate source and other email pattern flags. Multiple structure flags on one account increases confidence of templated signup.

---

### `DIGIT_SUFFIX`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email local part ends with 4–5 consecutive digits.

**When it triggers:** Local part ends with exactly 4 or 5 consecutive digits.

**Why it matters:** Bulk-generated accounts frequently append numeric suffixes to reuse a name stem across thousands of registrations.

**Scores (active):** 15 pts — Always when rule matches [digit_suffix]

**Investigation tips:** Look for SEQUENTIAL_EMAIL or NAME_NUMBER_PATTERN on the same affiliate; check IP velocity and shared IP.

---

### `SCRAMBLED_PATTERN`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email appears randomly generated (low vowel ratio, odd consonant runs).

**When it triggers:** Heuristic detects low vowel ratio and random-looking consonant clusters in the local part.

**Why it matters:** Automatically generated strings often lack natural language letter patterns. This catches machine-created inboxes that are not obviously name-based.

**Scores (active):** 35 pts — Always when rule matches [scrambled_pattern]

**Investigation tips:** High value combined with fast email validation or POV timing. Review profile images via CONTENT_REVIEW when present.

---

### `NAME_NUMBER_PATTERN`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Templated name+number local part (e.g. firstname12lastname4567@domain).

**When it triggers:** Local part matches firstname+number+lastname+number style templates.

**Why it matters:** One of the highest-yield automated rules: fraud operations use predictable name-and-number email templates across campaigns.

**Scores (active):** 40 pts — Always when rule matches [name_number_pattern]

**Investigation tips:** Prioritize for manual review; often appears in clusters from the same affiliate. Pair with sequential email detection.

---

### `WRITTEN_NUMBER_PATTERN`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Written numbers in the email local part (one, two, three, etc.).

**When it triggers:** Local part contains English written numbers (e.g. one, two, three).

**Why it matters:** Some generators embed spelled-out numbers to vary addresses while keeping a scriptable pattern.

**Scores (active):** 15 pts — Always when rule matches [written_number_pattern]

**Investigation tips:** Usually secondary signal; escalate when combined with other email flags.

---

### `REPEATED_WORD_PATTERN`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Word in local part appears in many emails in the current analysis batch.

**When it triggers:** A word from the local part appears in more than 3 emails in the current analysis batch (config: repeated_word_threshold).

**Why it matters:** Batch-level frequency detection finds shared tokens across many signups in the same run—common when a script reuses vocabulary.

**Scores (active):** 25 pts — Word frequency > threshold in batch [repeated_word_pattern]

**Investigation tips:** Inspect the repeated word in details; drill into affiliate and time window for the batch.

---

### `SUSPICIOUS_NAME`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Local part matches configured fraud-associated names list.

**When it triggers:** Local part contains a name from the configured suspicious_names list (default includes fatima, muhammed).

**Why it matters:** Names that recur disproportionately in confirmed fraud are flagged for review. List is editable in config.

**Scores (active):** 30 pts — Always when rule matches [suspicious_name]

**Investigation tips:** Validate against recent confirmed fraud outcomes; propose list updates monthly.

---

### `GENDER_NAME_MISMATCH`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Predicted gender from email/name does not match declared gender (user1).

**When it triggers:** Gender inferred from email/name (gender-guesser) conflicts with declared gender (user1/custom_u1), high-confidence only.

**Why it matters:** Declares one gender but uses an email local part strongly associated with another—common in misrepresented or scripted profiles.

**Scores (active):** 35 pts — High-confidence mismatch [gender_name_mismatch]

**Investigation tips:** Androgynous or unknown names are skipped. Confirm declared gender and billing name on paid accounts.

---

### `BILLING_GENDER_MISMATCH`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Paid records only: billing first name gender ≠ declared gender (high-confidence mismatches only).

**When it triggers:** Paid records: billing first name gender ≠ declared gender (high-confidence only).

**Why it matters:** Payment name inconsistent with profile gender is a strong paid-fraud indicator—often chargeback or stolen-card scenarios.

**Scores (active):** 35 pts — Paid data with high-confidence mismatch [billing_gender_mismatch]

**Investigation tips:** Cross-check shared_card flags and card type. Confirm with processor billing data.

---

### `theme_cluster`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email matches a theme bucket: REAL_ESTATE, CONSTRUCTION, CRYPTO, or FINANCE.

**When it triggers:** Local part contains keywords for real estate, construction, crypto, or finance themes.

**Why it matters:** Theme clustering groups niche keyword spam that appears in coordinated fraud waves (investment/crypto scams, etc.). Stored flag: THEME_CLUSTER_<THEME>.

**Scores (active):** 15 pts — Per matching theme [theme_cluster]

**Investigation tips:** Review campaign and affiliate; themes often spike together in time.

**Notes:** Stored as: THEME_CLUSTER_*

---

## Geographic clustering

### `SAME_US_STATE_CLUSTER`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** 3+ accounts from the same US state in batch.

**When it triggers:** 3+ accounts in batch share the same US state (geo from data).

**Why it matters:** Geographic clustering can indicate targeted fraud or proxy concentration.

**Scores (active):** 25 pts — 3+ accounts same US state [us_state_cluster]

**Investigation tips:** Compare to affiliate's expected geo; check city-level cluster flag.

---

### `SAME_US_CITY_STATE_CLUSTER`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** 3+ accounts from the same US city and state in batch.

**When it triggers:** 3+ accounts share same US city and state.

**Why it matters:** Tighter cluster than state-only—higher confidence of coordinated signups.

**Scores (active):** 30 pts — 3+ accounts same US city+state [us_city_state_cluster]

**Investigation tips:** Map to IP clusters and registration times.

---

### `SAME_INTL_COUNTRY_CITY_CLUSTER`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** 3+ accounts from the same international city in batch.

**When it triggers:** 3+ accounts share same non-US city.

**Why it matters:** International city clustering—common in outsourced fraud operations.

**Scores (active):** 30 pts — 3+ accounts same intl city [intl_country_city_cluster]

**Investigation tips:** Check login_high_risk_country and geo_login_mismatch.

---

## IP & device

### `IP_VELOCITY_HIGH`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Registration IP has 10+ signups in one hour (within analysis batch).

**When it triggers:** Registration IP has 10+ signups within one hour in the analysis batch (config: ip_velocity_threshold).

**Why it matters:** Classic fraud-ring signal—single IP driving volume in a short window.

**Scores (active):** 30 pts — 10+ signups/hour on IP [ip_velocity_high]

**Investigation tips:** Check SHARED_IP flags and datacenter/VPN ASN. Consider IP block at affiliate level.

---

### `IP_VELOCITY_MEDIUM`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Registration IP has 5+ signups in one hour (within analysis batch).

**When it triggers:** Registration IP has 5–9 signups within one hour in batch.

**Why it matters:** Elevated velocity; weaker alone but useful in combination.

**Scores (active):** 5 pts — 5+ signups/hour on IP [ip_velocity_medium]

**Investigation tips:** Trend IP over multiple days if data available.

---

### `SHARED_IP_HIGH`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Same registration IP used by 10+ accounts in batch.

**When it triggers:** Same registration IP appears on 10+ accounts in the batch.

**Why it matters:** Shared infrastructure—café, VPN, or fraud farm.

**Scores (active):** 35 pts — 10+ accounts share IP [shared_ip_high]

**Investigation tips:** Distinguish datacenter vs residential via enrichment flags.

---

### `SHARED_IP_MEDIUM`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Same registration IP used by 3–9 accounts in batch.

**When it triggers:** Same registration IP on 3–9 accounts in batch.

**Why it matters:** Moderate sharing; may be legitimate NAT but worth review on high-payout affiliates.

**Scores (active):** 20 pts — 3–9 accounts share IP [shared_ip_medium]

**Investigation tips:** Correlate with email patterns.

---

### `DESKTOP_DEVICE_SUSPICIOUS`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Desktop signup device; 20 pts Windows 10, 10 pts other desktops.

**When it triggers:** Signup user-agent indicates desktop; Windows 10 vs other desktop OS tiers.

**Why it matters:** Fraud farms often use Windows 10 desktops at scale; other desktops scored lower.

**Scores (active):** 20 pts — Windows 10 desktop [desktop_windows_10] | 10 pts — Other desktop OS [desktop_other]

**Investigation tips:** Combine with IP and email signals—desktop alone is weak.

**Notes:** Other desktop uses desktop_other config key.

---

## Manual review

### `CONTENT_REVIEW`

**Phase:** review_queue — Review workflow; may not add risk points.

**Summary:** Profile photo present and (upload <180s after registration OR suspicious email/identity flags) — content/image review queue.

**When it triggers:** Profile image uploaded AND (upload <180s after registration OR suspicious email/identity flags).

**Why it matters:** Queues accounts for manual image review (stock, stolen, AI faces)—not always a score driver (default 0 points).

**Scores (active):** 0 pts — Review queue match [content_review]

**Investigation tips:** Reverse image search; compare upload timing. Does not replace email/card investigation.

**Notes:** Stored as: CONTENT_REVIEW(+pts)?

---

## POV / verification timing (CSV)

### `POV_INSTANT_VALIDATION_20S`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email verified within 20 seconds (CSV POV fields).

**When it triggers:** CSV POV fields: email verified within 20 seconds of signup.

**Why it matters:** Human users rarely complete verification instantly; sub-20s timing suggests automation or pre-validated inboxes.

**Scores (active):** 50 pts — POV ≤ 20s [pov_instant_20s]

**Investigation tips:** Treat as critical if Admin email_validated timing confirms. Highest priority queue.

---

### `POV_INSTANT_VALIDATION_40S`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email verified within 40 seconds (CSV POV fields).

**When it triggers:** CSV POV: verified within 21–40 seconds.

**Why it matters:** Still abnormally fast for organic signup; slightly lower weight than 20s tier.

**Scores (active):** 40 pts — POV ≤ 40s [pov_instant_40s]

**Investigation tips:** Compare with Admin validation timestamps when available.

---

### `POV_FAST_VALIDATION_60S`

**Phase:** per_account — Applied to each row during lead/email analysis.

**Summary:** Email verified within 60 seconds (CSV POV fields).

**When it triggers:** CSV POV: verified within 41–60 seconds.

**Why it matters:** Fast validation band; meaningful when combined with other fraud signals.

**Scores (active):** 30 pts — POV ≤ 60s [pov_fast_60s]

**Investigation tips:** Use as supporting signal unless affiliate shows widespread fast POV.

---

## Pipeline phases (glossary)

- **per_account:** Applied to each row during lead/email analysis.
- **affiliate_batch:** Second pass on the analysis batch; only matching accounts are flagged.
- **admin_enrichment:** After Admin API + GeoIP enrichment (typically paid/enriched accounts).
- **post_enrichment:** Batch rule after enrichment completes (e.g. Discover concentration).
- **review_queue:** Review workflow; may not add risk points.
- **data_quality:** Data issue, not a fraud pattern.

- Total risk score is capped at 100.
- Point values below are defaults; live exports from the dashboard use config.json when available.
- Some Admin enrichment flags include detail in the stored string (e.g. ip_state_mismatch_CA→NY(+15)); the catalog_key groups variants.

