"""
Unit tests for the Selfie Search Lambda function.
"""

import base64
import json
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from conftest import load_handler

BUCKET_NAME = "test-wedding-media-bucket"
TABLE_NAME = "test-metadata-table"
COLLECTION_ID = "test-collection"

FAKE_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("MEDIA_BUCKET", BUCKET_NAME)
    monkeypatch.setenv("METADATA_TABLE", TABLE_NAME)
    monkeypatch.setenv("REKOGNITION_COLLECTION_ID", COLLECTION_ID)


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


def _build_event(selfie_b64: str) -> dict:
    return {
        "body": json.dumps({"selfie_image": selfie_b64}),
        "requestContext": {"authorizer": {"claims": {"sub": "user-999"}}},
    }


class TestSelfieSearch:

    def test_returns_matching_photos(self):
        """Returns photo metadata when face matches are found."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/photo-001_test.jpg",
                Body=FAKE_JPEG,
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            table.put_item(Item={
                "photo_id": "photo-001",
                "face_id": "face-guest-1",
                "s3_key": "uploads/user-123/photo-001_test.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "user-123",
                "content_type": "image/jpeg",
                "is_couple_photo": "false",
                "upload_timestamp": "2024-06-15T10:00:00+00:00",
            })

            h = load_handler("selfie_search")
            selfie_b64 = base64.b64encode(FAKE_JPEG).decode()
            mock_response = {
                "FaceMatches": [
                    {"Face": {"FaceId": "face-guest-1"}, "Similarity": 99.0}
                ]
            }
            with patch.object(h.rekognition, "search_faces_by_image", return_value=mock_response):
                response = h.lambda_handler(_build_event(selfie_b64), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 1
        assert body["matched_photos"][0]["photo_id"] == "photo-001"
        assert body["matched_photos"][0]["similarity"] == 99.0

    def test_no_matches_returns_empty_list(self):
        """Returns empty list when no face matches are found."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            selfie_b64 = base64.b64encode(FAKE_JPEG).decode()
            with patch.object(h.rekognition, "search_faces_by_image", return_value={"FaceMatches": []}):
                response = h.lambda_handler(_build_event(selfie_b64), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 0
        assert body["matched_photos"] == []

    def test_missing_selfie_image(self):
        """Returns 400 when selfie_image is missing."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            event = {"body": json.dumps({}), "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400
        assert "selfie_image" in json.loads(response["body"])["error"]

    def test_invalid_base64(self):
        """Returns 400 for invalid base64 data."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            event = {"body": json.dumps({"selfie_image": "not-valid-base64!!!!!"}), "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400

    def test_no_face_in_selfie(self):
        """Returns empty result gracefully when Rekognition finds no face in selfie."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            selfie_b64 = base64.b64encode(FAKE_JPEG).decode()
            exc = h.rekognition.exceptions.InvalidParameterException(
                {"Error": {"Code": "InvalidParameterException", "Message": "No face"}},
                "SearchFacesByImage",
            )
            with patch.object(h.rekognition, "search_faces_by_image", side_effect=exc):
                response = h.lambda_handler(_build_event(selfie_b64), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 0
        assert "No face detected" in body["message"]

    def test_image_too_large(self):
        """Returns 400 when the selfie image exceeds 5 MB."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            large_image = b"x" * (5 * 1024 * 1024 + 1)
            selfie_b64 = base64.b64encode(large_image).decode()
            response = h.lambda_handler(_build_event(selfie_b64), None)

        assert response["statusCode"] == 400
        assert "5 MB" in json.loads(response["body"])["error"]

    def test_cors_headers_present(self):
        """Response includes CORS headers."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("selfie_search")
            selfie_b64 = base64.b64encode(FAKE_JPEG).decode()
            with patch.object(h.rekognition, "search_faces_by_image", return_value={"FaceMatches": []}):
                response = h.lambda_handler(_build_event(selfie_b64), None)

        assert response["headers"]["Access-Control-Allow-Origin"] == "*"
