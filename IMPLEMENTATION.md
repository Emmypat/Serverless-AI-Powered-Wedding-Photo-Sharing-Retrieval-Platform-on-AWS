# Implementation Guide

This document walks through every step needed to provision, configure, and operate the
**Serverless AI-Powered Wedding Photo Sharing & Retrieval Platform** using either the
provided **Terraform** code or the **AWS SAM** template.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Repository Structure](#3-repository-structure)
4. [Choosing an IaC Approach](#4-choosing-an-iac-approach)
5. [Option A — Deploy with Terraform](#5-option-a--deploy-with-terraform)
   - [5.1 Configure AWS credentials](#51-configure-aws-credentials)
   - [5.2 Initialise Terraform](#52-initialise-terraform)
   - [5.3 Review the plan](#53-review-the-plan)
   - [5.4 Apply the infrastructure](#54-apply-the-infrastructure)
   - [5.5 Note the outputs](#55-note-the-outputs)
6. [Option B — Deploy with AWS SAM](#6-option-b--deploy-with-aws-sam)
7. [Post-Deployment Steps (both approaches)](#7-post-deployment-steps-both-approaches)
   - [7.1 Deploy the frontend](#71-deploy-the-frontend)
   - [7.2 Create the first admin/photographer account](#72-create-the-first-adminphotographer-account)
   - [7.3 Enrol the couple's faces](#73-enrol-the-couples-faces)
   - [7.4 Update CoupleFaceIds and re-deploy](#74-update-couplefaceids-and-re-deploy)
   - [7.5 Smoke-test the API](#75-smoke-test-the-api)
8. [Guest Workflow](#8-guest-workflow)
9. [Day-of-Wedding Checklist](#9-day-of-wedding-checklist)
10. [Updating the Platform](#10-updating-the-platform)
11. [Cost Estimate](#11-cost-estimate)
12. [Teardown / Cleanup](#12-teardown--cleanup)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Architecture Overview

```
Mobile / Browser
      │
      ▼
 CloudFront ──► S3 (frontend SPA)
      │
      ▼
 API Gateway  ──── Cognito User Pool (JWT auth)
      │
      ├── POST /upload-url        → UploadHandler λ  → presigned S3 PUT URL
      │                                               ↓
      │                                        S3 (media bucket)
      │                                               ↓
      │                             ProcessMedia λ (S3 trigger)
      │                                               ↓
      │                              Rekognition (IndexFaces)
      │                                               ↓
      │                               DynamoDB (face ↔ photo metadata)
      │
      ├── POST /search            → SelfieSearch λ
      │                              Rekognition (SearchFacesByImage)
      │                              DynamoDB (face-id-index GSI)
      │                              S3 presigned GET URLs
      │
      ├── GET  /couple-photos     → GetCouplePhotos λ
      │                              DynamoDB (couple-photos-index GSI)
      │                              S3 presigned GET URLs
      │
      ├── GET  /media             → ListMedia λ
      │                              DynamoDB (scan / uploader-index GSI)
      │                              S3 presigned GET URLs
      │
      └── DELETE /media/{id}      → DeleteMedia λ
                                     S3 delete + Rekognition delete + DynamoDB delete
```

**Key design decisions**

| Decision | Rationale |
|---|---|
| Presigned S3 URLs for uploads | Media bytes never pass through Lambda; handles large files efficiently |
| One DynamoDB record per (photo_id, face_id) | Enables the `face-id-index` GSI to map any Rekognition FaceId → photo in O(1) |
| `COUPLE_FACE_IDS` env var | Couple tagging is deploy-time config; update after face enrolment |
| CloudFront + S3 OAC for frontend | HTTPS everywhere; S3 bucket never exposed to the public internet |
| Cognito JWT on all API routes | Stateless auth; tokens carry the guest's `sub` identity claim |

---

## 2. Prerequisites

Install the following tools before proceeding:

| Tool | Minimum version | Install guide |
|---|---|---|
| AWS CLI | v2.x | https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html |
| Terraform | v1.6+ | https://developer.hashicorp.com/terraform/downloads |
| Python | 3.12 | https://www.python.org/downloads/ |
| AWS SAM CLI *(Option B only)* | v1.100+ | https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html |

You will also need:

- An **AWS account** with sufficient permissions to create IAM roles, S3 buckets, Lambda
  functions, API Gateway, CloudFront distributions, Cognito User Pools, DynamoDB tables,
  and Rekognition collections.
- A terminal (bash / zsh / PowerShell).

---

## 3. Repository Structure

```
.
├── frontend/               # Single-page application (HTML + CSS + JS)
│   ├── index.html
│   ├── css/styles.css
│   └── js/app.js
├── src/                    # Lambda function source code
│   ├── common/             # Shared utilities
│   ├── upload_handler/     # POST /upload-url
│   ├── process_media/      # S3-triggered face indexing
│   ├── selfie_search/      # POST /search
│   ├── get_couple_photos/  # GET /couple-photos
│   ├── list_media/         # GET /media
│   └── delete_media/       # DELETE /media/{photo_id}
├── terraform/              # Terraform IaC (this guide's primary path)
│   ├── main.tf             # Provider + backend config
│   ├── variables.tf        # Input variables
│   ├── locals.tf           # Computed locals
│   ├── outputs.tf          # Stack outputs
│   ├── s3.tf               # S3 buckets + policies + lifecycle
│   ├── cloudfront.tf       # CloudFront distribution + OAC
│   ├── cognito.tf          # Cognito User Pool + App Client
│   ├── dynamodb.tf         # DynamoDB table + GSIs
│   ├── iam.tf              # Lambda execution role + inline policy
│   ├── rekognition.tf      # Rekognition face collection
│   ├── lambda.tf           # Lambda functions + packaging + permissions
│   └── api_gateway.tf      # REST API + authorizer + routes + deployment
├── template.yaml           # AWS SAM template (Option B)
├── samconfig.toml          # SAM deployment defaults
├── Makefile                # Developer convenience targets
├── requirements.txt        # Python dev dependencies
└── tests/                  # Unit tests (pytest + moto)
```

---

## 4. Choosing an IaC Approach

| | Terraform | AWS SAM |
|---|---|---|
| **State management** | External state file (local or S3 backend) | CloudFormation manages state |
| **Lambda packaging** | `archive_file` data source (auto-zip on apply) | `sam build` compiles packages |
| **Local testing** | Use `sam local` separately for Lambda | `sam local start-api` built-in |
| **Best for** | Teams already using Terraform; multi-account pipelines | AWS-native workflows; rapid iteration |

Both produce an identical runtime architecture. Choose Terraform if your organisation
already manages infrastructure that way; choose SAM for a simpler, AWS-native experience.

---

## 5. Option A — Deploy with Terraform

### 5.1 Configure AWS credentials

```bash
# Method 1: AWS CLI named profile (recommended)
aws configure --profile wedding-platform
# → enter Access Key ID, Secret Access Key, region (e.g. us-east-1), output format (json)

export AWS_PROFILE=wedding-platform

# Method 2: Environment variables (CI/CD)
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-east-1"
```

Verify access:

```bash
aws sts get-caller-identity
```

### 5.2 Initialise Terraform

```bash
cd terraform/
terraform init
```

Expected output:

```
Initializing the backend...
Initializing provider plugins...
- Finding hashicorp/aws versions matching "~> 5.0"...
- Finding hashicorp/archive versions matching "~> 2.0"...
- Installed hashicorp/aws v5.x.x
- Installed hashicorp/archive v2.x.x
Terraform has been successfully initialized!
```

> **Tip — Remote state (recommended for teams)**
>
> Edit the `backend "s3"` block in `terraform/main.tf`, create the S3 bucket and DynamoDB
> lock table first, then re-run `terraform init`.

### 5.3 Review the plan

```bash
terraform plan \
  -var="stack_name=wedding-platform" \
  -var="environment=dev" \
  -var="aws_region=us-east-1"
```

Review the planned changes (expect ~40 resources to be created).

### 5.4 Apply the infrastructure

```bash
terraform apply \
  -var="stack_name=wedding-platform" \
  -var="environment=dev" \
  -var="aws_region=us-east-1"
```

Type `yes` when prompted. Provisioning takes approximately **3–5 minutes**.

> **Optional — Use a `terraform.tfvars` file** instead of passing `-var` flags:
>
> ```hcl
> # terraform/terraform.tfvars  (gitignored)
> stack_name  = "wedding-platform"
> environment = "dev"
> aws_region  = "us-east-1"
> ```
>
> Then simply run `terraform apply`.

### 5.5 Note the outputs

At the end of `terraform apply`, you will see:

```
Outputs:

api_endpoint              = "https://abc123.execute-api.us-east-1.amazonaws.com/dev"
cloudfront_url            = "https://d1234abcd.cloudfront.net"
media_bucket_name         = "wedding-media-123456789012-wedding-platform"
frontend_bucket_name      = "wedding-frontend-123456789012-wedding-platform"
user_pool_id              = "us-east-1_XXXXXXXXX"
user_pool_client_id       = "xxxxxxxxxxxxxxxxxxxxxxxxxx"
metadata_table_name       = "wedding-media-metadata-wedding-platform"
rekognition_collection_id = "wedding-faces-wedding-platform"
```

Save these values — you will need them in the next steps.

---

## 6. Option B — Deploy with AWS SAM

```bash
# 1. Install Python dependencies (test only; Lambda packages are bundled by SAM)
pip install -r requirements.txt

# 2. Build Lambda packages
sam build --parallel

# 3. Deploy (first time — interactive)
sam deploy --guided
#    Stack Name:        wedding-platform
#    Region:            us-east-1
#    Environment:       dev
#    CoupleFaceIds:     (leave blank for now)
#    Confirm changes:   y
#    Allow SAM to create IAM roles: y

# Subsequent deploys
sam deploy
```

SAM prints the same set of outputs at the end of the deploy.

---

## 7. Post-Deployment Steps (both approaches)

### 7.1 Deploy the frontend

The frontend is a static SPA that needs to know the API endpoint and Cognito IDs.
Edit `frontend/js/app.js` and update the config block at the top of the file:

```js
const CONFIG = {
  apiEndpoint:      'https://abc123.execute-api.us-east-1.amazonaws.com/dev',  // ← from outputs
  userPoolId:       'us-east-1_XXXXXXXXX',                                     // ← from outputs
  userPoolClientId: 'xxxxxxxxxxxxxxxxxxxxxxxxxx',                               // ← from outputs
  cloudfrontUrl:    'https://d1234abcd.cloudfront.net',                         // ← from outputs
};
```

Then sync to the frontend S3 bucket:

```bash
# Terraform output value
FRONTEND_BUCKET=$(terraform -chdir=terraform output -raw frontend_bucket_name)

aws s3 sync frontend/ s3://$FRONTEND_BUCKET/ --delete

# Invalidate the CloudFront cache
DISTRIBUTION_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Origins.Items[0].DomainName=='${FRONTEND_BUCKET}.s3.amazonaws.com'].Id" \
  --output text)

aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*"
```

The wedding platform is now live at the `cloudfront_url` output value.

### 7.2 Create the first admin/photographer account

```bash
USER_POOL_ID=$(terraform -chdir=terraform output -raw user_pool_id)

aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username photographer@example.com \
  --temporary-password "Temp1234!" \
  --user-attributes \
    Name=email,Value=photographer@example.com \
    Name=email_verified,Value=true \
    Name=given_name,Value=Photographer
```

The photographer must sign in through the web app and change the temporary password on
first login.

### 7.3 Enrol the couple's faces

This step registers the couple's faces in the Rekognition collection so that all photos
containing them can be tagged and surfaced automatically.

**Step 1** — Upload one clear portrait of the bride and one of the groom through the web
app (or directly to S3):

```bash
MEDIA_BUCKET=$(terraform -chdir=terraform output -raw media_bucket_name)
COLLECTION_ID=$(terraform -chdir=terraform output -raw rekognition_collection_id)

# Upload couple portraits directly to the media bucket
aws s3 cp bride_portrait.jpg \
  s3://$MEDIA_BUCKET/uploads/photographer/bride_portrait.jpg

aws s3 cp groom_portrait.jpg \
  s3://$MEDIA_BUCKET/uploads/photographer/groom_portrait.jpg
```

**Step 2** — The S3 upload triggers `process_media` automatically. The function indexes
the faces and writes records to DynamoDB. Retrieve the assigned `FaceId` values:

```bash
TABLE=$(terraform -chdir=terraform output -raw metadata_table_name)

# Find face IDs for uploads by the photographer account
aws dynamodb query \
  --table-name $TABLE \
  --index-name uploader-index \
  --key-condition-expression "uploaded_by = :uid" \
  --expression-attribute-values '{":uid":{"S":"photographer"}}' \
  --query "Items[*].face_id.S" \
  --output json
```

Note the `FaceId` strings returned (e.g. `"abc-123-def"`, `"xyz-456-ghi"`).

Alternatively, call Rekognition directly:

```bash
aws rekognition list-faces \
  --collection-id $COLLECTION_ID \
  --query "Faces[*].{FaceId:FaceId,ExternalImageId:ExternalImageId}" \
  --output table
```

### 7.4 Update CoupleFaceIds and re-deploy

Once you have the FaceIds for both members of the couple, re-deploy with the
`couple_face_ids` variable set:

**Terraform:**

```bash
terraform apply \
  -var="couple_face_ids=abc-123-def,xyz-456-ghi"
```

**SAM:**

```bash
sam deploy \
  --parameter-overrides \
    CoupleFaceIds="abc-123-def,xyz-456-ghi"
```

From this point on, every new upload that contains either face will automatically be
tagged as `is_couple_photo = true` and will appear in the `/couple-photos` feed.

To retroactively tag existing photos, re-process them:

```bash
# List all objects in the uploads/ prefix and re-trigger processing
aws s3api list-objects-v2 \
  --bucket $MEDIA_BUCKET \
  --prefix uploads/ \
  --query "Contents[*].Key" \
  --output text | tr '\t' '\n' | while read key; do
    # Copy object in-place to re-trigger the S3 notification
    aws s3 cp s3://$MEDIA_BUCKET/$key s3://$MEDIA_BUCKET/$key \
      --metadata-directive REPLACE
done
```

### 7.5 Smoke-test the API

Obtain a JWT token for the test user:

```bash
CLIENT_ID=$(terraform -chdir=terraform output -raw user_pool_client_id)
API=$(terraform -chdir=terraform output -raw api_endpoint)

TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id $CLIENT_ID \
  --auth-parameters USERNAME=photographer@example.com,PASSWORD='NewPassword1!' \
  --query "AuthenticationResult.IdToken" \
  --output text)

# Test: request a presigned upload URL
curl -s -X POST "$API/upload-url" \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_name":"test.jpg","content_type":"image/jpeg"}' | jq .

# Test: list all media
curl -s "$API/media" \
  -H "Authorization: $TOKEN" | jq .

# Test: list couple photos
curl -s "$API/couple-photos" \
  -H "Authorization: $TOKEN" | jq .
```

---

## 8. Guest Workflow

1. **Register** — Guest opens the CloudFront URL and creates an account with their email.
2. **Upload** — Guest taps "Upload Photos", selects images/videos from their phone.
   The app requests a presigned URL, then PUTs the file directly to S3.
3. **Processing** — S3 triggers `process_media` within seconds. Faces are indexed;
   couple photos are tagged automatically.
4. **Find yourself** — Guest taps "Find My Photos", takes a selfie, and receives a
   gallery of every wedding photo they appear in.
5. **Browse** — Guest browses the full wedding gallery and downloads favourites.
6. **Couple photos** — Any guest can view the curated couple gallery at any time.

---

## 9. Day-of-Wedding Checklist

- [ ] All infrastructure deployed and outputs recorded
- [ ] Frontend deployed and CloudFront cache invalidated
- [ ] Couple's FaceIds enrolled and `CoupleFaceIds` re-deployed
- [ ] Smoke-test API from a real mobile browser
- [ ] Test upload of one photo from a smartphone
- [ ] Verify photo appears in `/media` within 30 seconds
- [ ] Verify selfie search returns the uploaded photo
- [ ] Brief the photographer — upload portraits from the `uploads/photographer/` prefix
- [ ] Share the CloudFront URL with guests (QR code on tables is effective)

---

## 10. Updating the Platform

### Update Lambda code only

**Terraform:**

```bash
# Edit source files, then:
terraform apply   # archive_file detects changes via source_code_hash
```

**SAM:**

```bash
sam build && sam deploy
```

### Update infrastructure + code

Re-run `terraform apply` or `sam deploy` after editing `.tf` / `template.yaml` files.

---

## 11. Cost Estimate

Based on a 100-guest wedding with ~500 photo uploads and 200 selfie searches:

| Service | Usage | Estimated cost |
|---|---|---|
| Lambda | ~1,000 invocations × 256 MB × 1 s avg | < $0.01 |
| API Gateway | ~2,000 requests | < $0.01 |
| S3 | ~5 GB storage + ~1,000 GET/PUT requests | ~$0.15 |
| DynamoDB | PAY_PER_REQUEST; ~5,000 write units | < $0.01 |
| Rekognition | 500 IndexFaces + 200 SearchFacesByImage | ~$0.80 |
| CloudFront | ~500 MB transferred | < $0.10 |
| **Total** | | **~$1–6 / event** |

---

## 12. Teardown / Cleanup

> ⚠️ **This is irreversible.** All media, metadata, and user accounts will be deleted.

**Terraform:**

```bash
# Empty the S3 buckets first (S3 buckets with objects cannot be destroyed by Terraform)
MEDIA_BUCKET=$(terraform -chdir=terraform output -raw media_bucket_name)
FRONTEND_BUCKET=$(terraform -chdir=terraform output -raw frontend_bucket_name)

aws s3 rm s3://$MEDIA_BUCKET   --recursive
aws s3 rm s3://$FRONTEND_BUCKET --recursive

# Destroy all infrastructure
terraform destroy
```

**SAM / CloudFormation:**

```bash
aws s3 rm s3://$(aws cloudformation describe-stacks \
  --stack-name wedding-platform \
  --query "Stacks[0].Outputs[?OutputKey=='MediaBucketName'].OutputValue" \
  --output text) --recursive

sam delete --stack-name wedding-platform --no-prompts
```

---

## 13. Troubleshooting

### Lambda function times out on S3 trigger

Increase the `process_media` timeout. In Terraform:

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "process_media" {
  timeout = 120   # was 60
  ...
}
```

### CORS errors in the browser

Ensure the API Gateway stage has been **deployed** after any method/integration changes.
In Terraform, the `triggers` block in `aws_api_gateway_deployment.wedding` handles this
automatically on `terraform apply`.

### Rekognition returns `ResourceNotFoundException`

The face collection was not created before `process_media` ran. The Lambda handler
automatically creates the collection if it does not exist, but verify the collection
exists:

```bash
aws rekognition describe-collection \
  --collection-id $(terraform -chdir=terraform output -raw rekognition_collection_id)
```

### `InvalidParameterException` from Rekognition (no face detected)

This is expected for photos with no detectable faces (landscapes, objects, etc.).
The Lambda handler writes a `face_id = "NO_FACE"` record for these images, which is
correct behaviour.

### Presigned URL upload returns 403

The presigned URL has expired (default: 1 hour) or the `Content-Type` header in the PUT
request does not exactly match the one used to generate the URL. Ensure the browser sets
the same `Content-Type` in the upload request.

### CloudFront returns stale frontend after a re-deploy

Create a cache invalidation:

```bash
aws cloudfront create-invalidation \
  --distribution-id <DISTRIBUTION_ID> \
  --paths "/*"
```
