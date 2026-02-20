"""
Selfie Search Lambda Function

Allows a wedding guest to find all photos they appear in by uploading
a selfie image (base64-encoded).

POST /search
Request body:
  {
    "selfie_image": "<base64-encoded image bytes>",
    "content_type": "image/jpeg"   (optional, default image/jpeg)
  }

Response:
  {
    "matched_photos": [
      {
        "photo_id": "uuid",
        "download_url": "https://...",
        "content_type": "image/jpeg",
        "uploaded_by": "user-sub",
        "upload_timestamp": "2024-01-01T12:00:00+00:00",
        "similarity": 99.5
      },
      ...
    ],
    "total": 3
  }

The function:
1. Calls Rekognition SearchFacesByImage with the uploaded selfie.
2. Collects unique photo_ids from the face matches.
3. Fetches metadata for each photo from DynamoDB.
4. Generates presigned S3 GET URLs for the matched photos.
"""

import base64
import json
import logging
import os
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MEDIA_BUCKET = os.environ["MEDIA_BUCKET"]
METADATA_TABLE = os.environ["METADATA_TABLE"]
COLLECTION_ID = os.environ["REKOGNITION_COLLECTION_ID"]
DOWNLOAD_URL_EXPIRY = int(os.environ.get("DOWNLOAD_URL_EXPIRY", "86400"))
FACE_MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "80.0"))

rekognition = boto3.client("rekognition")
dynamodb = boto3.resource("dynamodb")
s3_client = boto3.client("s3")


def lambda_handler(event: dict, context) -> dict:
    """
    Search for wedding photos matching the provided selfie.

    :param event: API Gateway proxy event
    :param context: Lambda context object
    :return: API Gateway proxy response with matching photo URLs
    """
    logger.info("Received selfie search request")

    # ── Parse request ─────────────────────────────────────────────────────────
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error("Invalid JSON in request body", 400)

    selfie_b64 = body.get("selfie_image", "").strip()
    if not selfie_b64:
        return _error("selfie_image (base64-encoded) is required", 400)

    try:
        image_bytes = base64.b64decode(selfie_b64)
    except Exception:
        return _error("selfie_image must be valid base64-encoded image data", 400)

    if len(image_bytes) > 5 * 1024 * 1024:
        return _error("Selfie image must be smaller than 5 MB", 400)

    # ── Search Rekognition collection ─────────────────────────────────────────
    try:
        response = rekognition.search_faces_by_image(
            CollectionId=COLLECTION_ID,
            Image={"Bytes": image_bytes},
            FaceMatchThreshold=FACE_MATCH_THRESHOLD,
            MaxFaces=1000,
        )
    except rekognition.exceptions.InvalidParameterException:
        return _success({"matched_photos": [], "total": 0, "message": "No face detected in the selfie image."})
    except rekognition.exceptions.ResourceNotFoundException:
        return _success({"matched_photos": [], "total": 0, "message": "No photos have been processed yet."})
    except ClientError as exc:
        logger.error("Rekognition search failed: %s", exc)
        return _error("Face search failed. Please try again.", 500)

    face_matches = response.get("FaceMatches", [])
    logger.info("Rekognition returned %d face match(es)", len(face_matches))

    if not face_matches:
        return _success({"matched_photos": [], "total": 0, "message": "No matching photos found."})

    # ── Collect unique photos and best similarity scores ──────────────────────
    # face_id -> similarity (keep the highest similarity for deduplication)
    best_similarity: dict[str, float] = {}
    for match in face_matches:
        face_id = match["Face"]["FaceId"]
        similarity = match["Similarity"]
        if face_id not in best_similarity or similarity > best_similarity[face_id]:
            best_similarity[face_id] = similarity

    # ── Look up metadata in DynamoDB ──────────────────────────────────────────
    table = dynamodb.Table(METADATA_TABLE)
    photo_results: dict[str, dict] = {}  # photo_id -> result dict

    for face_id, similarity in best_similarity.items():
        items = _query_by_face_id(table, face_id)
        for item in items:
            photo_id = item["photo_id"]
            if photo_id in photo_results:
                # Keep the highest similarity score for this photo
                if similarity > photo_results[photo_id]["similarity"]:
                    photo_results[photo_id]["similarity"] = round(similarity, 2)
            else:
                s3_key = item.get("s3_key", "")
                download_url = _presign_url(s3_key)
                photo_results[photo_id] = {
                    "photo_id": photo_id,
                    "download_url": download_url,
                    "content_type": item.get("content_type", "image/jpeg"),
                    "uploaded_by": item.get("uploaded_by", ""),
                    "upload_timestamp": item.get("upload_timestamp", ""),
                    "similarity": round(similarity, 2),
                }

    matched = sorted(
        photo_results.values(),
        key=lambda x: x["similarity"],
        reverse=True,
    )

    logger.info("Returning %d matched photo(s)", len(matched))
    return _success({"matched_photos": matched, "total": len(matched)})


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _query_by_face_id(table, face_id: str) -> list[dict]:
    """Query the DynamoDB face-id-index GSI for all photos containing a face."""
    try:
        response = table.query(
            IndexName="face-id-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("face_id").eq(face_id),
        )
        return response.get("Items", [])
    except ClientError as exc:
        logger.error("DynamoDB query failed for face_id=%s: %s", face_id, exc)
        return []


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
        logger.error("Could not generate presigned URL for %s: %s", s3_key, exc)
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
