"""
Upload Handler Lambda Function

Generates a presigned S3 URL that allows guests to upload their photo or
video directly from the browser/mobile app to S3, avoiding any data
passing through Lambda.

POST /upload-url
Request body:
  {
    "file_name": "photo.jpg",
    "content_type": "image/jpeg"
  }

Response:
  {
    "upload_url": "https://s3.amazonaws.com/...",
    "photo_id": "uuid",
    "s3_key": "uploads/<user_id>/<uuid>_photo.jpg"
  }
"""

import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
UPLOAD_URL_EXPIRY = int(os.environ.get("UPLOAD_URL_EXPIRY", "3600"))

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
    "video/webm",
}

s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """
    Generate a presigned S3 PUT URL for direct client upload.

    :param event: API Gateway proxy event
    :param context: Lambda context object
    :return: API Gateway proxy response
    """
    logger.info("Received upload URL request")

    # Parse request body
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error("Invalid JSON in request body", 400)

    file_name = body.get("file_name", "").strip()
    content_type = body.get("content_type", "").strip().lower()

    # Validate inputs
    if not file_name:
        return _error("file_name is required", 400)
    if not content_type:
        return _error("content_type is required", 400)
    if content_type not in ALLOWED_CONTENT_TYPES:
        return _error(
            f"Unsupported content type '{content_type}'. "
            f"Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
            400,
        )

    # Sanitise the file name (keep only the base name to prevent path traversal)
    safe_file_name = os.path.basename(file_name)
    if not safe_file_name:
        return _error("Invalid file_name", 400)

    # Derive the caller identity from Cognito (falls back to 'anonymous')
    user_id = _get_user_id(event)

    # Build a unique S3 key: uploads/<user_id>/<uuid>_<filename>
    photo_id = str(uuid.uuid4())
    s3_key = f"uploads/{user_id}/{photo_id}_{safe_file_name}"

    try:
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": MEDIA_BUCKET,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=UPLOAD_URL_EXPIRY,
        )
    except ClientError as exc:
        logger.error("Failed to generate presigned URL: %s", exc)
        return _error("Could not generate upload URL. Please try again.", 500)

    logger.info("Generated presigned URL for key=%s user=%s", s3_key, user_id)
    return _success(
        {
            "upload_url": presigned_url,
            "photo_id": photo_id,
            "s3_key": s3_key,
        },
        201,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_user_id(event: dict) -> str:
    """Extract the Cognito sub claim (unique user identifier) from the event."""
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
        return claims.get("sub", "anonymous")
    except (KeyError, TypeError):
        return "anonymous"


def _success(body: dict, status_code: int = 200) -> dict:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps(body),
    }


def _error(message: str, status_code: int = 400) -> dict:
    return {
        "statusCode": status_code,
        "headers": _cors_headers(),
        "body": json.dumps({"error": message}),
    }


def _cors_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }
