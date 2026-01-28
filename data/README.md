# Data Directory

Place your CSV exports in this directory before running fraud detection scripts.

## Required Files

### Leads.csv
Export from affiliate tracking platform with these columns:
- `email` - Affiliate email address
- `IP` - Registration IP address
- `DUID` - Unique account ID
- `username` - Account username
- `payout amount` - Affiliate payout amount
- `campaign` - Campaign identifier
- `Ad Id` - Advertisement identifier
- `transaction date` - Date of transaction

### Sales.csv (for cross-reference analysis)
Export from payment processor with these columns:
- `first name` - Customer first name
- `last name` - Customer last name
- `email` - Customer email
- `IP` - Transaction IP address
- `sale amount` - Transaction amount
- `payout amount` - Affiliate payout
- `campaign` - Campaign identifier
- `DUID` - Unique account ID
- `Ad Id` - Advertisement identifier
- `transaction date` - Date of transaction

## Optional Enhancement Fields

For email validation timing analysis, manually add these columns to Leads.csv:
- `account_creation_timestamp` - When account was created (ISO format: YYYY-MM-DD HH:MM:SS)
- `email_validation_timestamp` - When email was validated (ISO format: YYYY-MM-DD HH:MM:SS)

The script will automatically calculate validation timing and flag accounts validated < 60 seconds after creation.

## Sample Data Format

Example Leads.csv:
```
email,IP,DUID,username,payout amount,campaign,Ad Id,transaction date
john.doe.test.1234@example.com,192.168.1.1,ACC001,johndoe,50.00,CAMP_A,AD123,2025-12-01
real.estate.agent.5678@realty.com,192.168.1.2,ACC002,realestate,75.00,CAMP_B,AD456,2025-12-01
legitimate@gmail.com,192.168.1.3,ACC003,legit,25.00,CAMP_A,AD789,2025-12-02
```

## Data Privacy

- DO NOT commit actual customer data to version control
- This directory is included in .gitignore
- Treat all CSV files as sensitive information
