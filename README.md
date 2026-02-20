# Serverless AI-Powered Wedding Photo Sharing & Retrieval Platform on AWS

A fully serverless, mobile-friendly wedding photo sharing platform built on AWS.  
Wedding guests can **upload photos and short videos** from their smartphones, **find every photo they appear in** by uploading a selfie, and **automatically browse curated couple photos** — all powered by Amazon Rekognition AI facial recognition.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Guest / Photographer                           │
│                    (Mobile Browser or Desktop)                          │
└──────────────────────────┬─────────────────────────────────────────────┘
                           │  HTTPS
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       Amazon CloudFront (CDN)                            │
│           Static Frontend (S3) · SSL Termination · Edge Cache           │
└────────────┬─────────────────────────────────────────┬──────────────────┘
             │ Static Assets                            │ API Requests
             ▼                                          ▼
┌─────────────────────┐              ┌──────────────────────────────────┐
│  Amazon S3          │              │  Amazon API Gateway (REST)       │
│  (Frontend Bucket)  │              │  + Cognito JWT Authorizer        │
└─────────────────────┘              └──────┬───────────────────────────┘
                                            │
                    ┌───────────────────────┼────────────────────────┐
                    │                       │                        │
                    ▼                       ▼                        ▼
         ┌──────────────────┐  ┌─────────────────────┐  ┌────────────────────┐
         │  Lambda:         │  │  Lambda:             │  │  Lambda:           │
         │  upload_handler  │  │  selfie_search       │  │  get_couple_photos │
         │  (presign URL)   │  │  (face search)       │  │  (curated gallery) │
         └────────┬─────────┘  └──────────┬──────────┘  └────────────────────┘
                  │                        │
                  ▼                        │        ┌────────────────────────┐
         ┌──────────────┐                  │        │  Lambda: list_media    │
         │  Amazon S3   │◄─── PUT ─────────┘        │  (browse all media)    │
         │  (Media      │                            └────────────────────────┘
         │   Bucket)    │
         └──────┬───────┘                            ┌────────────────────────┐
                │ S3 Event                            │  Lambda: delete_media  │
                │ (ObjectCreated)                     │  (remove photo)        │
                ▼                                     └────────────────────────┘
         ┌──────────────────┐
         │  Lambda:         │──► Amazon Rekognition ──► Index Faces in Collection
         │  process_media   │                           Search Faces by Image
         │  (face indexing) │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │  Amazon DynamoDB │  (MediaMetadataTable)
         │  photo metadata  │  Indexes: face-id, uploader, couple-photos
         └──────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                       Amazon Cognito User Pool                          │
│              Guest registration · Sign-in · JWT tokens                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Key AWS Services

| Service | Purpose |
|---|---|
| **Amazon S3** | Store media uploads; host static frontend |
| **Amazon CloudFront** | CDN for frontend; SSL; edge caching |
| **Amazon API Gateway** | RESTful API, CORS, JWT authorization |
| **AWS Lambda (Python 3.12)** | All backend business logic |
| **Amazon Rekognition** | Face detection, indexing, and search |
| **Amazon DynamoDB** | Photo metadata with GSI for fast queries |
| **Amazon Cognito** | Guest authentication and JWT tokens |
| **AWS SAM** | Infrastructure as Code deployment |

---

## Features

- 📸 **Direct S3 uploads** — presigned PUT URLs let guests upload from the browser without data passing through Lambda
- 🤖 **AI facial recognition** — Amazon Rekognition indexes every face and enables selfie-based photo retrieval
- 💑 **Couple photos** — photos are automatically tagged when the couple's faces are detected
- 🔐 **Secure access** — Cognito authentication, HTTPS-only S3 policy, presigned download URLs
- 📱 **Mobile-first UI** — responsive HTML/CSS/JS frontend optimised for smartphones
- ♾️ **Serverless & scalable** — handles high concurrent traffic during the wedding with zero infrastructure management
- 💰 **Cost-efficient** — pay-per-use Lambda + DynamoDB On-Demand pricing; S3 lifecycle rules move media to IA after 90 days

---

## Project Structure

```
.
├── template.yaml                  # AWS SAM infrastructure template
├── frontend/
│   ├── index.html                 # Single-page application
│   ├── css/styles.css             # Mobile-first responsive styles
│   └── js/app.js                  # Client-side logic (auth, upload, search)
├── src/
│   ├── upload_handler/handler.py  # POST /upload-url  – presigned S3 URL
│   ├── process_media/handler.py   # S3 trigger – Rekognition face indexing
│   ├── selfie_search/handler.py   # POST /search     – find photos by selfie
│   ├── get_couple_photos/handler.py # GET /couple-photos
│   ├── list_media/handler.py      # GET /media
│   ├── delete_media/handler.py    # DELETE /media/{photo_id}
│   └── common/utils.py            # Shared utilities
└── tests/
    ├── requirements.txt
    └── unit/
        ├── test_upload_handler.py
        ├── test_process_media.py
        ├── test_selfie_search.py
        ├── test_get_couple_photos.py
        └── test_list_media.py
```

---

## API Reference

All endpoints require a valid Cognito `IdToken` in the `Authorization` header (except CORS preflight).

### `POST /upload-url`
Generate a presigned S3 URL for direct media upload.

**Request:**
```json
{
  "file_name": "photo.jpg",
  "content_type": "image/jpeg"
}
```

**Response (201):**
```json
{
  "upload_url": "https://s3.amazonaws.com/...",
  "photo_id": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key": "uploads/<user_id>/<photo_id>_photo.jpg"
}
```

After receiving the `upload_url`, the client performs a `PUT` request directly to S3.

---

### `POST /search`
Find all wedding photos a guest appears in by uploading a selfie.

**Request:**
```json
{
  "selfie_image": "<base64-encoded JPEG/PNG>",
  "content_type": "image/jpeg"
}
```

**Response (200):**
```json
{
  "matched_photos": [
    {
      "photo_id": "...",
      "download_url": "https://...",
      "content_type": "image/jpeg",
      "uploaded_by": "user-sub",
      "upload_timestamp": "2024-06-15T14:30:00+00:00",
      "similarity": 99.2
    }
  ],
  "total": 5
}
```

---

### `GET /couple-photos`
Return curated photos featuring the couple.

**Query parameters:** `limit` (default 50), `cursor` (pagination)

**Response (200):**
```json
{
  "photos": [ { "photo_id": "...", "download_url": "...", ... } ],
  "total": 12,
  "next_cursor": null
}
```

---

### `GET /media`
Browse all wedding photos and videos.

**Query parameters:** `limit`, `cursor`, `uploaded_by`

**Response (200):**
```json
{
  "media": [ { "photo_id": "...", "download_url": "...", "is_couple_photo": false, ... } ],
  "total": 48,
  "next_cursor": "eyJwaG90b19pZCI..."
}
```

---

### `DELETE /media/{photo_id}`
Delete a photo (uploader only).

**Response (200):**
```json
{ "message": "Photo deleted successfully." }
```

---

## Deployment

### Prerequisites

- AWS CLI configured (`aws configure`)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.12
- An AWS account

### 1. Clone and install test dependencies

```bash
pip install -r tests/requirements.txt
```

### 2. Run unit tests

```bash
pytest tests/unit/ -v
```

### 3. Deploy with SAM

```bash
# Build the application
sam build

# Deploy interactively (first time)
sam deploy --guided --stack-name wedding-platform --region us-east-1

# Or deploy with parameters
sam deploy \
  --stack-name wedding-platform \
  --region us-east-1 \
  --parameter-overrides \
    Environment=prod \
    CoupleFaceIds="face-id-1,face-id-2" \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
```

### 4. Register the couple's faces

After deployment, upload a photo of the couple and note the `FaceId` values from DynamoDB. Then redeploy with the `CoupleFaceIds` parameter:

```bash
sam deploy \
  --stack-name wedding-platform \
  --parameter-overrides CoupleFaceIds="face-id-from-rekognition-1,face-id-from-rekognition-2" \
  --no-confirm-changeset
```

### 5. Deploy the frontend

```bash
# Get output values
API_URL=$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text)
FRONTEND_BUCKET=$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text)
CLOUDFRONT_URL=$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text)
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)
USER_POOL_CLIENT=$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)

# Inject configuration into frontend
sed -i \
  "s|https://YOUR_API_GATEWAY_URL/dev|${API_URL}|g;
   s|us-east-1_EXAMPLE|${USER_POOL_ID}|g;
   s|EXAMPLE_CLIENT_ID|${USER_POOL_CLIENT}|g" \
  frontend/js/app.js

# Upload frontend to S3
aws s3 sync frontend/ s3://${FRONTEND_BUCKET}/ --delete

echo "Platform live at: ${CLOUDFRONT_URL}"
```

### 6. Clean up

```bash
# Delete all media from the bucket first
aws s3 rm s3://$(aws cloudformation describe-stacks --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='MediaBucketName'].OutputValue" --output text) --recursive

sam delete --stack-name wedding-platform
```

---

## Security

- All S3 buckets block public access; media is accessed only via time-limited presigned URLs
- S3 bucket policy enforces HTTPS-only (`aws:SecureTransport`)
- API Gateway endpoints require valid Cognito JWT tokens
- Photo deletion is restricted to the original uploader
- Selfie image bytes (sent for search) are held only in Lambda memory and never persisted
- DynamoDB point-in-time recovery is enabled
- CloudFront uses Origin Access Control (OAC) to prevent direct S3 access

---

## Cost Estimate (100-guest wedding)

| Service | Estimated Usage | Cost |
|---|---|---|
| S3 | ~10 GB media | ~$0.23/month |
| Lambda | ~5,000 invocations | < $0.01 |
| API Gateway | ~5,000 requests | ~$0.02 |
| Rekognition | ~500 face indexings + searches | ~$1.25 |
| DynamoDB | ~5,000 writes/reads | < $0.01 |
| CloudFront | ~50 GB transfer | ~$4.25 |
| Cognito | Up to 50,000 MAUs free tier | $0 |
| **Total** | | **~$6/month** |

---

## Development & Testing

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Run all unit tests
pytest tests/unit/ -v

# Run a specific test file
pytest tests/unit/test_upload_handler.py -v

# Run tests with coverage
pytest tests/unit/ --cov=src --cov-report=term-missing
```

The tests use [moto](https://github.com/getmoto/moto) to mock AWS services locally.

---

## License

MIT