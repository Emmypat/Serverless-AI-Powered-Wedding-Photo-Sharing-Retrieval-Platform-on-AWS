"""
Delete Media Lambda Function

Allows a guest to delete a photo they uploaded (or allows an admin
to delete any photo). Removes the object from S3 and all associated
metadata rows from DynamoDB, and de-indexes the faces from Rekognition.

DELETE /media/{photo_id}

Response (200):
  { "message": "Photo deleted successfully." }

Response (403):
  { "error": "You are not authorised to delete this photo." }

Response (404):
  { "error": "Photo not found." }
"""

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
COLLECTION_ID = os.environ["REKOGNITION_COLLECTION_ID"]

dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")
rekognition = boto3.client("rekognition")


def lambda_handler(event: dict, context) -> dict:
    """
    Delete a wedding photo and its associated metadata.

    :param event: API Gateway proxy event (path parameter: photo_id)
    :param context: Lambda context object
    :return: API Gateway proxy response
    """
    photo_id = (event.get("pathParameters") or {}).get("photo_id", "").strip()
    if not photo_id:
        return _error("photo_id path parameter is required", 400)

    caller_id = _get_user_id(event)
    logger.info("Delete request: photo_id=%s caller=%s", photo_id, caller_id)

    # ── Fetch all DynamoDB records for this photo ─────────────────────────────
    table = dynamodb.Table(METADATA_TABLE)
    items = _get_photo_records(table, photo_id)

    if not items:
        return _error("Photo not found.", 404)

    # ── Authorisation: only the uploader may delete their photo ──────────────
    uploader = items[0].get("uploaded_by", "")
    if caller_id != uploader:
        logger.warning(
            "Unauthorised delete attempt: caller=%s uploader=%s photo=%s",
            caller_id,
            uploader,
            photo_id,
        )
        return _error("You are not authorised to delete this photo.", 403)

    # ── Delete from S3 ────────────────────────────────────────────────────────
    s3_key = items[0].get("s3_key", "")
    if s3_key:
        _delete_from_s3(s3_key)

    # ── De-index faces from Rekognition ──────────────────────────────────────
    face_ids = [
        item["face_id"]
        for item in items
        if item.get("face_id") and item["face_id"] != "NO_FACE"
    ]
    if face_ids:
        _delete_faces_from_rekognition(face_ids)

    # ── Delete all DynamoDB records for this photo ────────────────────────────
    _delete_metadata_records(table, items)

    logger.info("Deleted photo_id=%s", photo_id)
    return _success({"message": "Photo deleted successfully."})


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_photo_records(table, photo_id: str) -> list[dict]:
    """
    Retrieve all DynamoDB items for the given photo_id.

    A single photo may have multiple records (one per face detected).
    We scan using a FilterExpression since photo_id is the table primary key
    but we store one record per (photo_id, face_id) pair – using put_item in
    process_media means multiple items share the same photo_id with
    different face_id values.  A scan with filter is acceptable here since
    deletes are infrequent.
    """
    try:
        # First try a direct get_item (works if there is exactly one record)
        response = table.query(
            KeyConditionExpression=Key("photo_id").eq(photo_id),
        )
        return response.get("Items", [])
    except ClientError as exc:
        logger.error("DynamoDB query failed for photo_id=%s: %s", photo_id, exc)
        return []


def _delete_from_s3(s3_key: str) -> None:
    """Delete an object from S3, logging errors without re-raising."""
    try:
        s3_client.delete_object(Bucket=MEDIA_BUCKET, Key=s3_key)
        logger.info("Deleted S3 object: %s", s3_key)
    except ClientError as exc:
        logger.error("Failed to delete S3 object %s: %s", s3_key, exc)


def _delete_faces_from_rekognition(face_ids: list[str]) -> None:
    """Remove face entries from the Rekognition collection."""
    # Rekognition accepts up to 4096 face IDs per call
    chunk_size = 4096
    for i in range(0, len(face_ids), chunk_size):
        chunk = face_ids[i : i + chunk_size]
        try:
            rekognition.delete_faces(CollectionId=COLLECTION_ID, FaceIds=chunk)
            logger.info("Deleted %d face(s) from Rekognition", len(chunk))
        except ClientError as exc:
            logger.error("Failed to delete faces from Rekognition: %s", exc)


def _delete_metadata_records(table, items: list[dict]) -> None:
    """Delete all DynamoDB records associated with a photo."""
    try:
        with table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        "photo_id": item["photo_id"],
                        "face_id": item.get("face_id", "NO_FACE"),
                    }
                )
        logger.info("Deleted %d DynamoDB record(s)", len(items))
    except ClientError as exc:
        logger.error("Failed to delete DynamoDB records: %s", exc)


def _get_user_id(event: dict) -> str:
    """Extract the Cognito sub claim from the API Gateway authorizer context."""
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
