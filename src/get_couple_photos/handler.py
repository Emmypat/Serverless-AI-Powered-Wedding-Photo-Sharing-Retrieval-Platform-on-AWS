"""
Get Couple Photos Lambda Function

Returns presigned download URLs for all wedding photos that were
automatically tagged as containing the couple (i.e. their faces appear
in the Rekognition collection and their FaceIds are listed in the
COUPLE_FACE_IDS environment variable, or photos were manually tagged
during the process_media step).

GET /couple-photos
Query parameters (optional):
  limit   – maximum number of results to return (default 50, max 200)
  cursor  – pagination cursor (last_evaluated_key, base64-encoded JSON)

Response:
  {
    "photos": [
      {
        "photo_id": "uuid",
        "download_url": "https://...",
        "content_type": "image/jpeg",
        "uploaded_by": "user-sub",
        "upload_timestamp": "2024-01-01T12:00:00+00:00"
      },
      ...
    ],
    "total": 20,
    "next_cursor": "<base64 string or null>"
  }
"""

import base64
import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
METADATA_TABLE = os.environ["METADATA_TABLE"]
DOWNLOAD_URL_EXPIRY = int(os.environ.get("DOWNLOAD_URL_EXPIRY", "86400"))
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """
    Return presigned URLs for all couple photos.

    :param event: API Gateway proxy event
    :param context: Lambda context object
    :return: API Gateway proxy response
    """
    logger.info("Received couple-photos request")

    # ── Parse query parameters ────────────────────────────────────────────────
    params = event.get("queryStringParameters") or {}
    try:
        limit = min(int(params.get("limit", DEFAULT_PAGE_LIMIT)), MAX_PAGE_LIMIT)
    except ValueError:
        return _error("'limit' must be an integer", 400)

    cursor_b64 = params.get("cursor")
    exclusive_start_key = None
    if cursor_b64:
        try:
            exclusive_start_key = json.loads(base64.b64decode(cursor_b64).decode())
        except Exception:
            return _error("Invalid pagination cursor", 400)

    # ── Query DynamoDB couple-photos-index GSI ────────────────────────────────
    table = dynamodb.Table(METADATA_TABLE)
    query_kwargs = {
        "IndexName": "couple-photos-index",
        "KeyConditionExpression": Key("is_couple_photo").eq("true"),
        "Limit": limit,
        "ScanIndexForward": False,  # most recent first
    }
    if exclusive_start_key:
        query_kwargs["ExclusiveStartKey"] = exclusive_start_key

    try:
        response = table.query(**query_kwargs)
    except ClientError as exc:
        logger.error("DynamoDB query failed: %s", exc)
        return _error("Could not retrieve couple photos. Please try again.", 500)

    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")

    # Deduplicate by photo_id (multiple DynamoDB records per photo, one per face)
    seen: set[str] = set()
    photos = []
    for item in items:
        photo_id = item.get("photo_id", "")
        if photo_id in seen:
            continue
        seen.add(photo_id)

        s3_key = item.get("s3_key", "")
        photos.append(
            {
                "photo_id": photo_id,
                "download_url": _presign_url(s3_key),
                "content_type": item.get("content_type", "image/jpeg"),
                "uploaded_by": item.get("uploaded_by", ""),
                "upload_timestamp": item.get("upload_timestamp", ""),
            }
        )

    # ── Build next-page cursor ────────────────────────────────────────────────
    next_cursor = None
    if last_key:
        next_cursor = base64.b64encode(json.dumps(last_key).encode()).decode()

    logger.info("Returning %d couple photo(s)", len(photos))
    return _success(
        {
            "photos": photos,
            "total": len(photos),
            "next_cursor": next_cursor,
        }
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _presign_url(s3_key: str) -> str:
    """Generate a presigned GET URL for the given S3 key."""
    if not s3_key:
        return ""
    try:
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": MEDIA_BUCKET, "Key": s3_key},
            ExpiresIn=DOWNLOAD_URL_EXPIRY,
        )
    except ClientError as exc:
        logger.error("Could not presign URL for %s: %s", s3_key, exc)
        return ""


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
