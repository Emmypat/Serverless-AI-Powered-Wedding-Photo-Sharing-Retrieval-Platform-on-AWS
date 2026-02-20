"""
Process Media Lambda Function

Triggered automatically by S3 when a new object is created under the
``uploads/`` prefix. Performs:

1. Face detection via Amazon Rekognition (images only).
2. Indexes each detected face into the Rekognition collection.
3. Checks whether any face belongs to the couple (via COUPLE_FACE_IDS env var).
4. Writes photo metadata – including all face IDs – to DynamoDB.

This function is NOT exposed via API Gateway; it is an event-driven
background processor.
"""

import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
METADATA_TABLE = os.environ["METADATA_TABLE"]
COLLECTION_ID = os.environ["REKOGNITION_COLLECTION_ID"]
COUPLE_FACE_IDS_RAW = os.environ.get("COUPLE_FACE_IDS", "")

COUPLE_FACE_IDS: set[str] = {
    fid.strip() for fid in COUPLE_FACE_IDS_RAW.split(",") if fid.strip()
}

REKOGNITION_SUPPORTED_TYPES = {"image/jpeg", "image/jpg", "image/png"}

rekognition = boto3.client("rekognition")
dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> None:
    """
    Process S3 ObjectCreated events.

    :param event: S3 event notification
    :param context: Lambda context object
    """
    _ensure_collection_exists()

    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        key = urllib.parse.unquote_plus(s3_info.get("object", {}).get("key", ""))

        if not bucket or not key:
            logger.warning("Skipping record with missing bucket/key: %s", record)
            continue

        logger.info("Processing s3://%s/%s", bucket, key)
        _process_object(bucket, key)


# ─── Core processing ─────────────────────────────────────────────────────────


def _process_object(bucket: str, key: str) -> None:
    """Index faces in the uploaded object and persist metadata to DynamoDB."""

    # Derive photo_id and uploader from the S3 key: uploads/<user_id>/<photo_id>_<filename>
    parts = key.split("/")
    user_id = parts[1] if len(parts) >= 3 else "unknown"
    filename_part = parts[2] if len(parts) >= 3 else parts[-1]
    photo_id = filename_part.split("_")[0] if "_" in filename_part else filename_part

    # Determine content type
    content_type = _get_content_type(bucket, key)
    is_image = content_type.lower() in REKOGNITION_SUPPORTED_TYPES

    face_ids: list[str] = []
    is_couple_photo = False

    if is_image:
        face_ids = _index_faces(bucket, key, photo_id)
        is_couple_photo = bool(COUPLE_FACE_IDS & set(face_ids))

    timestamp = datetime.now(timezone.utc).isoformat()

    _write_metadata(
        photo_id=photo_id,
        s3_key=key,
        bucket=bucket,
        uploaded_by=user_id,
        content_type=content_type,
        face_ids=face_ids,
        is_couple_photo=is_couple_photo,
        upload_timestamp=timestamp,
    )

    logger.info(
        "Processed photo_id=%s faces=%d couple_photo=%s",
        photo_id,
        len(face_ids),
        is_couple_photo,
    )


def _index_faces(bucket: str, key: str, photo_id: str) -> list[str]:
    """
    Call Rekognition IndexFaces to detect and index faces in the image.
    Returns a list of FaceId strings.
    """
    try:
        response = rekognition.index_faces(
            CollectionId=COLLECTION_ID,
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            ExternalImageId=photo_id,
            DetectionAttributes=["DEFAULT"],
            QualityFilter="AUTO",
        )
        face_ids = [
            record["Face"]["FaceId"]
            for record in response.get("FaceRecords", [])
        ]
        logger.info("Indexed %d face(s) for key=%s", len(face_ids), key)
        return face_ids
    except rekognition.exceptions.InvalidParameterException:
        # No faces detected – normal for landscape/decoration photos
        logger.info("No faces detected in %s", key)
        return []
    except ClientError as exc:
        logger.error("Rekognition IndexFaces failed for %s: %s", key, exc)
        return []


def _write_metadata(
    *,
    photo_id: str,
    s3_key: str,
    bucket: str,
    uploaded_by: str,
    content_type: str,
    face_ids: list[str],
    is_couple_photo: bool,
    upload_timestamp: str,
) -> None:
    """Persist photo metadata to DynamoDB."""
    table = dynamodb.Table(METADATA_TABLE)

    # Write one record per face so the face-id-index GSI can be queried per face
    if face_ids:
        with table.batch_writer() as batch:
            for face_id in face_ids:
                batch.put_item(
                    Item={
                        "photo_id": photo_id,
                        "face_id": face_id,
                        "s3_key": s3_key,
                        "bucket": bucket,
                        "uploaded_by": uploaded_by,
                        "content_type": content_type,
                        "is_couple_photo": "true" if is_couple_photo else "false",
                        "upload_timestamp": upload_timestamp,
                        "face_count": len(face_ids),
                    }
                )
    else:
        # Photos with no detected faces (e.g. videos, landscape shots)
        table.put_item(
            Item={
                "photo_id": photo_id,
                "face_id": "NO_FACE",
                "s3_key": s3_key,
                "bucket": bucket,
                "uploaded_by": uploaded_by,
                "content_type": content_type,
                "is_couple_photo": "false",
                "upload_timestamp": upload_timestamp,
                "face_count": 0,
            }
        )


def _get_content_type(bucket: str, key: str) -> str:
    """Return the ContentType of an S3 object, defaulting to 'application/octet-stream'."""
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
        return head.get("ContentType", "application/octet-stream")
    except ClientError:
        return "application/octet-stream"


def _ensure_collection_exists() -> None:
    """Create the Rekognition face collection if it does not already exist."""
    try:
        rekognition.describe_collection(CollectionId=COLLECTION_ID)
    except rekognition.exceptions.ResourceNotFoundException:
        logger.info("Creating Rekognition collection: %s", COLLECTION_ID)
        rekognition.create_collection(CollectionId=COLLECTION_ID)
    except ClientError as exc:
        logger.error("Could not ensure Rekognition collection exists: %s", exc)
