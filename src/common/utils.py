"""
Common utilities shared across all Lambda functions.
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
    "video/webm",
}

ALLOWED_CONTENT_TYPES = ALLOWED_IMAGE_CONTENT_TYPES | ALLOWED_VIDEO_CONTENT_TYPES

# Rekognition supports JPEG and PNG for face detection/indexing
REKOGNITION_SUPPORTED_TYPES = {"image/jpeg", "image/jpg", "image/png"}

# Maximum presigned URL expiry (1 hour for uploads, 24 hours for downloads)
UPLOAD_URL_EXPIRY = 3600
DOWNLOAD_URL_EXPIRY = 86400


def build_response(status_code: int, body: Any, headers: dict | None = None) -> dict:
    """Build a standard API Gateway response with CORS headers."""
    default_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    }
    if headers:
        default_headers.update(headers)

    return {
        "statusCode": status_code,
        "headers": default_headers,
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def success_response(body: Any, status_code: int = 200) -> dict:
    """Return a 200 OK response."""
    return build_response(status_code, body)


def error_response(message: str, status_code: int = 400) -> dict:
    """Return an error response."""
    return build_response(status_code, {"error": message})


def get_caller_identity(event: dict) -> str:
    """
    Extract the caller's identity from the API Gateway authorizer context.
    Returns the Cognito sub (unique user ID).
    """
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
        return claims.get("sub", "anonymous")
    except (KeyError, TypeError):
        return "anonymous"


def is_image(content_type: str) -> bool:
    """Return True if the content type is a supported image format."""
    return content_type.lower() in ALLOWED_IMAGE_CONTENT_TYPES


def is_video(content_type: str) -> bool:
    """Return True if the content type is a supported video format."""
    return content_type.lower() in ALLOWED_VIDEO_CONTENT_TYPES


def rekognition_supported(content_type: str) -> bool:
    """Return True if Rekognition can process this content type for face detection."""
    return content_type.lower() in REKOGNITION_SUPPORTED_TYPES
