"""
Unit tests for the Get Couple Photos Lambda function.
"""

import base64
import json
import os

import boto3
import pytest
from moto import mock_aws

from conftest import load_handler

BUCKET_NAME = "test-wedding-media-bucket"
TABLE_NAME = "test-metadata-table"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("MEDIA_BUCKET", BUCKET_NAME)
    monkeypatch.setenv("METADATA_TABLE", TABLE_NAME)
    monkeypatch.setenv("REKOGNITION_COLLECTION_ID", "test-collection")


def _make_ddb_table(ddb):
    return ddb.create_table(
        TableName=TABLE_NAME,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "photo_id", "AttributeType": "S"},
            {"AttributeName": "face_id", "AttributeType": "S"},
            {"AttributeName": "uploaded_by", "AttributeType": "S"},
            {"AttributeName": "is_couple_photo", "AttributeType": "S"},
            {"AttributeName": "upload_timestamp", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "photo_id", "KeyType": "HASH"},
            {"AttributeName": "face_id", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "face-id-index",
                "KeySchema": [
                    {"AttributeName": "face_id", "KeyType": "HASH"},
                    {"AttributeName": "upload_timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "uploader-index",
                "KeySchema": [
                    {"AttributeName": "uploaded_by", "KeyType": "HASH"},
                    {"AttributeName": "upload_timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "couple-photos-index",
                "KeySchema": [
                    {"AttributeName": "is_couple_photo", "KeyType": "HASH"},
                    {"AttributeName": "upload_timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


class TestGetCouplePhotos:

    def test_returns_only_couple_photos(self):
        """Returns only photos tagged as couple photos, deduplicated by photo_id."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(Bucket=BUCKET_NAME, Key="uploads/photographer/couple-photo-001_wedding.jpg", Body=b"img")

            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            # Two records for same photo (two faces)
            for face_id in ("face-bride", "face-groom"):
                table.put_item(Item={
                    "photo_id": "couple-photo-001",
                    "face_id": face_id,
                    "s3_key": "uploads/photographer/couple-photo-001_wedding.jpg",
                    "bucket": BUCKET_NAME,
                    "uploaded_by": "photographer",
                    "content_type": "image/jpeg",
                    "is_couple_photo": "true",
                    "upload_timestamp": "2024-06-15T14:00:00+00:00",
                })
            # Non-couple photo
            table.put_item(Item={
                "photo_id": "guest-photo-002",
                "face_id": "face-guest-3",
                "s3_key": "uploads/user-456/guest-photo-002_fun.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "user-456",
                "content_type": "image/jpeg",
                "is_couple_photo": "false",
                "upload_timestamp": "2024-06-15T15:00:00+00:00",
            })

            h = load_handler("get_couple_photos")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 1
        assert body["photos"][0]["photo_id"] == "couple-photo-001"

    def test_presigned_url_generated(self):
        """Each returned photo includes a non-empty download_url."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(Bucket=BUCKET_NAME, Key="uploads/photographer/couple-photo-001_wedding.jpg", Body=b"img")

            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            table.put_item(Item={
                "photo_id": "couple-photo-001",
                "face_id": "face-bride",
                "s3_key": "uploads/photographer/couple-photo-001_wedding.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "photographer",
                "content_type": "image/jpeg",
                "is_couple_photo": "true",
                "upload_timestamp": "2024-06-15T14:00:00+00:00",
            })

            h = load_handler("get_couple_photos")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        body = json.loads(response["body"])
        assert body["photos"][0]["download_url"] != ""

    def test_invalid_limit_parameter(self):
        """Returns 400 for a non-integer limit parameter."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("get_couple_photos")
            event = {"queryStringParameters": {"limit": "abc"}, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "'limit'" in json.loads(response["body"])["error"]

    def test_cors_headers_present(self):
        """Response includes CORS headers."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("get_couple_photos")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_pagination_cursor_returned(self):
        """Returns next_cursor when more results are available."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)

            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            # Add two couple photos
            for i, (photo_id, face_id, ts) in enumerate([
                ("couple-001", "face-bride-1", "2024-06-15T14:00:00+00:00"),
                ("couple-003", "face-bride-3", "2024-06-15T16:00:00+00:00"),
            ]):
                s3.put_object(Bucket=BUCKET_NAME, Key=f"uploads/p/{photo_id}.jpg", Body=b"img")
                table.put_item(Item={
                    "photo_id": photo_id,
                    "face_id": face_id,
                    "s3_key": f"uploads/p/{photo_id}.jpg",
                    "bucket": BUCKET_NAME,
                    "uploaded_by": "photographer",
                    "content_type": "image/jpeg",
                    "is_couple_photo": "true",
                    "upload_timestamp": ts,
                })

            h = load_handler("get_couple_photos")
            event = {"queryStringParameters": {"limit": "1"}, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "next_cursor" in body
