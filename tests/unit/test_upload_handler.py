"""
Unit tests for the Upload Handler Lambda function.
"""

import json
import os

import boto3
import pytest
from moto import mock_aws

from conftest import load_handler

BUCKET_NAME = "test-wedding-media-bucket"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Set fake AWS credentials and required environment variables."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("MEDIA_BUCKET", BUCKET_NAME)
    monkeypatch.setenv("METADATA_TABLE", "test-metadata-table")
    monkeypatch.setenv("REKOGNITION_COLLECTION_ID", "test-collection")


@pytest.fixture
def s3_and_handler():
    """Provide a mock S3 bucket and the freshly loaded upload handler."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)
        h = load_handler("upload_handler")
        yield s3, h


def _build_event(body: dict, user_sub: str = "user-123") -> dict:
    return {
        "body": json.dumps(body),
        "requestContext": {"authorizer": {"claims": {"sub": user_sub}}},
    }


class TestUploadHandler:

    def test_valid_jpeg_upload(self, s3_and_handler):
        """Generates a presigned URL for a valid JPEG upload request."""
        _, h = s3_and_handler
        event = _build_event({"file_name": "photo.jpg", "content_type": "image/jpeg"})
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "upload_url" in body
        assert "photo_id" in body
        assert "s3_key" in body
        assert body["s3_key"].startswith("uploads/user-123/")
        assert "photo.jpg" in body["s3_key"]

    def test_valid_video_upload(self, s3_and_handler):
        """Generates a presigned URL for a valid MP4 video upload request."""
        _, h = s3_and_handler
        event = _build_event({"file_name": "clip.mp4", "content_type": "video/mp4"})
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "upload_url" in body
        assert body["s3_key"].startswith("uploads/user-123/")

    def test_missing_file_name(self, s3_and_handler):
        """Returns 400 when file_name is missing."""
        _, h = s3_and_handler
        event = _build_event({"content_type": "image/jpeg"})
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "file_name" in json.loads(response["body"])["error"]

    def test_missing_content_type(self, s3_and_handler):
        """Returns 400 when content_type is missing."""
        _, h = s3_and_handler
        event = _build_event({"file_name": "photo.jpg"})
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "content_type" in json.loads(response["body"])["error"]

    def test_unsupported_content_type(self, s3_and_handler):
        """Returns 400 for unsupported content types."""
        _, h = s3_and_handler
        event = _build_event({"file_name": "file.pdf", "content_type": "application/pdf"})
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "Unsupported content type" in json.loads(response["body"])["error"]

    def test_path_traversal_prevention(self, s3_and_handler):
        """Sanitises the file_name to prevent path traversal attacks."""
        _, h = s3_and_handler
        event = _build_event(
            {"file_name": "../../etc/passwd", "content_type": "image/jpeg"}
        )
        response = h.lambda_handler(event, None)

        # os.path.basename strips the traversal; resulting name is 'passwd'
        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert ".." not in body["s3_key"]

    def test_invalid_json_body(self, s3_and_handler):
        """Returns 400 for malformed JSON body."""
        _, h = s3_and_handler
        event = {"body": "not-json", "requestContext": {}}
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "Invalid JSON" in json.loads(response["body"])["error"]

    def test_cors_headers_present(self, s3_and_handler):
        """Response includes CORS headers."""
        _, h = s3_and_handler
        event = _build_event({"file_name": "photo.jpg", "content_type": "image/jpeg"})
        response = h.lambda_handler(event, None)

        assert response["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_anonymous_user(self, s3_and_handler):
        """Falls back to 'anonymous' when Cognito claims are absent."""
        _, h = s3_and_handler
        event = {
            "body": json.dumps({"file_name": "photo.jpg", "content_type": "image/jpeg"}),
            "requestContext": {},
        }
        response = h.lambda_handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert "uploads/anonymous/" in body["s3_key"]
