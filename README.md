# Webhook Pharow → Odoo + Cloud Tasks

A Flask application that receives webhook payloads from Pharow, converts them into Odoo CRM leads with duplicate detection, and queues mail generation tasks in Google Cloud Tasks.

## Features

- **Pharow to Odoo mapping**: Converts Pharow prospect data into Odoo lead format
- **Duplicate detection**: Checks if a lead already exists before creating it
- **Smart address parsing**: Extracts street, zip code, and city from full addresses
- **Rich lead descriptions**: Builds detailed descriptions with company and person information
- **Cloud Tasks integration**: Automatically queues mail generation tasks for each new lead
- **Cloud Run ready**: Configured for deployment on Google Cloud Run

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `ODOO_DB_URL` | Base URL of your Odoo instance | ✅ | `https://www.lightandshutter.fr` |
| `ODOO_SECRET` | API token for Odoo authentication | ✅ | `Bearer token...` |
| `GCP_PROJECT_ID` | Google Cloud Project ID | ✅ | `my-project-123` |
| `GCP_REGION` | Google Cloud region | ❌ | `europe-west1` (default) |
| `CLOUD_TASKS_QUEUE` | Cloud Tasks queue name | ❌ | `mail-writer-queue` (default) |
| `MAIL_WRITER_ENDPOINT` | URL of the mail-writer service | ✅ | `https://mail-writer-xxx.a.run.app` |

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

## Cloud Tasks Integration

After successfully creating leads in Odoo, the webhook automatically creates tasks in Google Cloud Tasks. Each task calls the mail-writer service to generate a personalized prospection email.

### How it works:

1. **Pharow webhook received** → Leads created in Odoo
2. **For each new lead** → Cloud Tasks queues a mail generation task
3. **Cloud Tasks** → Calls the mail-writer service with:
   ```json
   {
     "first_name": "John",
     "last_name": "Doe",
     "email": "john.doe@example.com",
     "website": "https://www.example.com",
     "partner_name": "Example Inc.",
     "function": "Marketing Director",
     "description": "Leading innovative software solutions"
   }
   ```
4. **Mail-writer service** → Generates subject and body, then creates a Gmail draft
5. **Gmail Draft** → Ready to be reviewed and sent

### Cloud Tasks Queue Setup

Before deploying, create a Cloud Tasks queue:

```bash
gcloud tasks queues create mail-writer-queue \
  --location=europe-west1 \
  --max-dispatches-per-second=10 \
  --max-concurrent-dispatches=5
```

### Response with Cloud Tasks

Successful response now includes task creation info:

```json
{
  "status": "ok",
  "odoo_status": "ok",
  "odoo_response": {
    "id": 12345,
    "tasks_created": [
      {
        "status": "task_created",
        "task_name": "projects/my-project/locations/europe-west1/queues/mail-writer-queue/tasks/abc123..."
      }
    ]
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

### Prerequisites

1. Create the Cloud Tasks queue:
```bash
gcloud tasks queues create mail-writer-queue \
  --location=europe-west1 \
  --max-dispatches-per-second=10 \
  --max-concurrent-dispatches=5
```

2. Get the mail-writer service URL (if already deployed):
```bash
gcloud run services describe mail-writer --region europe-west1 --format='value(status.url)'
```

### Deploy the webhook service

```bash
gcloud run deploy pharow-to-odoo \
  --source . \
  --region europe-west1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --set-env-vars \
    ODOO_DB_URL="https://your-odoo-instance.com",\
    ODOO_SECRET="your-api-token",\
    GCP_PROJECT_ID="your-gcp-project-id",\
    GCP_REGION="europe-west1",\
    CLOUD_TASKS_QUEUE="mail-writer-queue",\
    MAIL_WRITER_ENDPOINT="https://mail-writer-xxx.a.run.app"
```

### Grant necessary IAM permissions

The Cloud Run service account needs permission to create tasks:

```bash
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member=serviceAccount:pharow-to-odoo@your-gcp-project-id.iam.gserviceaccount.com \
  --role=roles/cloudtasks.enqueuer
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

### Cloud Tasks Not Created
1. Verify `GCP_PROJECT_ID` is set correctly
2. Verify `MAIL_WRITER_ENDPOINT` is set and accessible
3. Check that the Cloud Run service account has `roles/cloudtasks.enqueuer` permission
4. Verify the Cloud Tasks queue exists:
   ```bash
   gcloud tasks queues list --location=europe-west1
   ```
5. Check Cloud Logging for Cloud Tasks errors

### Debugging Cloud Tasks

View queue stats:
```bash
gcloud tasks queues describe mail-writer-queue --location=europe-west1
```

View task details:
```bash
gcloud tasks list --queue=mail-writer-queue --location=europe-west1
```

View Cloud Logging:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=pharow-to-odoo" --limit=50 --format=json
```

## Logging

All operations are logged with prefixes:
- `[DEBUG]` - Debug information
- `[INFO]` - General information
- `[ERROR]` - Error messages

## License

Proprietary - Light and Shutter
