# Webhook Pharow → Odoo

A Flask application that receives webhook payloads from Pharow and converts them into Odoo CRM leads, with duplicate detection.

## Features

- **Pharow to Odoo mapping**: Converts Pharow prospect data into Odoo lead format
- **Duplicate detection**: Checks if a lead already exists before creating it
- **Smart address parsing**: Extracts street, zip code, and city from full addresses
- **Rich lead descriptions**: Builds detailed descriptions with company and person information
- **Cloud Run ready**: Configured for deployment on Google Cloud Run

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ODOO_DB_URL` | Base URL of your Odoo instance | `https://www.lightandshutter.fr` |
| `ODOO_SECRET` | API token for authentication | `Bearer token...` |

## API Endpoints

### POST `/`
Receives a Pharow webhook payload and creates leads in Odoo.

**Request body:**
```json
{
  "data": [
    {
      "position": {
        "pharowListName": "List name",
        "positionJobTitle": "Job title",
        "positionEmail": "contact@example.com",
        "positionEmailStatus": "valid",
        "positionEmailReliability": "95%"
      },
      "person": {
        "personLastName": "Doe",
        "personFirstName": "John",
        "personSalutation": "Mr",
        "personLinkedinUrl": "https://linkedin.com/in/john-doe",
        "personMobilePhone": "",
        "personPhoneKaspr1": "",
        "personPhoneKaspr3": "",
        "personMobilePhoneBettercontact": "",
        "personPhoneFullenrich1": "",
        "personPhoneFullenrich3": ""
      },
      "company": {
        "pharowCompanyId": "1306199",
        "companySiren": "500933452",
        "companyHqSiret": "50093345200046",
        "companyBrandName": "Company Name",
        "companyName": "Company Name",
        "companyLinkedinName": "Company Name",
        "companyMainPhone": "+33 1 23 45 67 89",
        "companyMainPhoneOrigin": "Dropcontact",
        "companyGenericEmail": "contact@company.com",
        "companyNafSector": "Software development",
        "companyActivity": "Software development",
        "companyFoundingYear": "2007",
        "companyFoundingDate": "2007-10-12",
        "companyGrowing": true,
        "companyNbEmployees": "",
        "companyEmployeeRangeCorrected": "50 - 99",
        "companyUrl": "https://www.company.com",
        "companyLinkedinUrl": "https://linkedin.com/company/company",
        "companyHqFullAddress": "89 Street Name 75000 Paris",
        "companyAnnualRevenueEuros": "5265034",
        "companyAnnualRevenueYear": "2021"
      }
    }
  ],
  "version": "V2"
}
```

**Response:**
```json
{
  "status": "ok",
  "odoo_status": "ok|skipped|error",
  "odoo_response": {
    "id": 12345,
    ...
  }
}
```

## Odoo Configuration

### Required Fields
- `name` - Lead name (auto-generated: "🎥 Idée de vidéo pour {brand}")
- `type` - Always set to "lead"
- `contact_name` - Contact person's full name
- `partner_name` - Company name
- `function` - Job title
- `email_from` - Contact email
- `phone` - Company phone
- `website` - Company website
- `street` - Street address
- `zip` - Postal code
- `city` - City name
- `description` - Rich description with company details
- `source_id` - Source ID (default: 25 for "Pharow")

### Custom Fields Required
- `x_external_id` - Stores the Pharow Company ID for duplicate detection

### Source Setup
Ensure source ID 25 exists in Odoo with name "Pharow", or update `source_id` value in the code.

## Duplicate Detection

Before creating a lead, the system searches Odoo for existing leads with the same `x_external_id` (Pharow Company ID). If found, the webhook returns:

```json
{
  "status": "ok",
  "odoo_status": "skipped",
  "odoo_response": {
    "status": "skipped",
    "reason": "Lead with external_id '1306199' already exists",
    "existing_ids": [12345]
  }
}
```

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ODOO_DB_URL="https://your-odoo-instance.com"
export ODOO_SECRET="your-api-token"

# Run the Flask app
python main.py
```

The app will be available at `http://localhost:8080`

## Deployment on Cloud Run

```bash
gcloud run deploy webhook-test \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars ODOO_DB_URL="https://your-odoo-instance.com",ODOO_SECRET="your-api-token"
```

## Troubleshooting

### 500 Error from Odoo
Check the logs for detailed error messages. The app logs:
- Request URL and payload
- HTTP status code and response headers
- Full error messages and tracebacks

### Lead Not Created
1. Verify `ODOO_DB_URL` and `ODOO_SECRET` are correctly set
2. Check if lead already exists (duplicate detection)
3. Verify required Odoo fields exist and custom field `x_external_id` is created
4. Check address parsing - ensure the address format is recognized

### Address Not Parsed
The parser expects format: `{number} {street} {zipcode} {city}`
Example: `89 Rue Nationale 59000 Lille`

## Logging

All operations are logged with prefixes:
- `[DEBUG]` - Debug information
- `[INFO]` - General information
- `[ERROR]` - Error messages

## License

Proprietary - Light and Shutter
