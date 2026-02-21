"""
List Media Lambda Function

Returns a paginated list of all wedding photos and videos with presigned
download URLs. Supports optional filtering by uploader.

GET /media
Query parameters (optional):
  limit       – max results per page (default 50, max 200)
  cursor      – pagination cursor (base64-encoded JSON)
  uploaded_by – filter to media uploaded by a specific user (Cognito sub)

Response:
  {
    "media": [
      {
        "photo_id": "uuid",
        "download_url": "https://...",
        "content_type": "image/jpeg",
        "uploaded_by": "user-sub",
        "upload_timestamp": "2024-01-01T12:00:00+00:00",
        "is_couple_photo": false
      },
      ...
    ],
    "total": 10,
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
    List all wedding media with presigned download URLs.

    :param event: API Gateway proxy event
    :param context: Lambda context object
    :return: API Gateway proxy response
    """
    logger.info("Received list-media request")

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

    uploaded_by = params.get("uploaded_by", "").strip()

    # ── Query DynamoDB ────────────────────────────────────────────────────────
    table = dynamodb.Table(METADATA_TABLE)

    if uploaded_by:
        items, last_key = _query_by_uploader(table, uploaded_by, limit, exclusive_start_key)
    else:
        items, last_key = _scan_all(table, limit, exclusive_start_key)

    # ── Deduplicate by photo_id ───────────────────────────────────────────────
    seen: set[str] = set()
    media_list = []
    for item in items:
        photo_id = item.get("photo_id", "")
        if photo_id in seen:
            continue
        seen.add(photo_id)

        s3_key = item.get("s3_key", "")
        media_list.append(
            {
                "photo_id": photo_id,
                "download_url": _presign_url(s3_key),
                "content_type": item.get("content_type", "image/jpeg"),
                "uploaded_by": item.get("uploaded_by", ""),
                "upload_timestamp": item.get("upload_timestamp", ""),
                "is_couple_photo": item.get("is_couple_photo", "false") == "true",
            }
        )

    # ── Build next-page cursor ────────────────────────────────────────────────
    next_cursor = None
    if last_key:
        next_cursor = base64.b64encode(json.dumps(last_key).encode()).decode()

    logger.info("Returning %d media item(s)", len(media_list))
    return _success(
        {
            "media": media_list,
            "total": len(media_list),
            "next_cursor": next_cursor,
        }
    )


# ─── DynamoDB helpers ─────────────────────────────────────────────────────────


def _query_by_uploader(
    table,
    uploaded_by: str,
    limit: int,
    exclusive_start_key: dict | None,
) -> tuple[list[dict], dict | None]:
    """Query the uploader-index GSI for media from a specific user."""
    kwargs = {
        "IndexName": "uploader-index",
        "KeyConditionExpression": Key("uploaded_by").eq(uploaded_by),
        "Limit": limit,
        "ScanIndexForward": False,
    }
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key
    try:
        response = table.query(**kwargs)
        return response.get("Items", []), response.get("LastEvaluatedKey")
    except ClientError as exc:
        logger.error("DynamoDB query failed: %s", exc)
        return [], None


def _scan_all(
    table,
    limit: int,
    exclusive_start_key: dict | None,
) -> tuple[list[dict], dict | None]:
    """Scan the entire table (all media). Used when no uploader filter is set."""
    kwargs = {"Limit": limit}
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key
    try:
        response = table.scan(**kwargs)
        return response.get("Items", []), response.get("LastEvaluatedKey")
    except ClientError as exc:
        logger.error("DynamoDB scan failed: %s", exc)
        return [], None


# ─── S3 helper ───────────────────────────────────────────────────────────────


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
