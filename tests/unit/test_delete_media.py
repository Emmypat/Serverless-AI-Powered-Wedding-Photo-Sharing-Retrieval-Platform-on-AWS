"""
Unit tests for the Delete Media Lambda function.
"""

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


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Set fake AWS credentials and required environment variables."""
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


def _seed_photo(table, s3, photo_id="photo-abc", face_id="face-001",
                uploader="user-alice", s3_key=None):
    """Insert a photo record into DynamoDB and its object into S3."""
    if s3_key is None:
        s3_key = f"uploads/{uploader}/{photo_id}_img.jpg"
    table.put_item(Item={
        "photo_id": photo_id,
        "face_id": face_id,
        "s3_key": s3_key,
        "bucket": BUCKET_NAME,
        "uploaded_by": uploader,
        "content_type": "image/jpeg",
        "is_couple_photo": "false",
        "upload_timestamp": "2024-06-15T14:00:00+00:00",
    })
    s3.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=b"fake-image-data")


def _build_event(photo_id: str, user_sub: str = "user-alice") -> dict:
    return {
        "pathParameters": {"photo_id": photo_id},
        "requestContext": {"authorizer": {"claims": {"sub": user_sub}}},
    }


class TestDeleteMedia:

    def test_owner_can_delete_photo(self):
        """Returns 200 when the photo owner deletes their own photo."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            _seed_photo(table, s3)

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={"DeletedFaces": ["face-001"]}):
                response = h.lambda_handler(_build_event("photo-abc", "user-alice"), None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "Photo deleted successfully."

    def test_non_owner_cannot_delete_photo(self):
        """Returns 403 when a different user attempts to delete the photo."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            _seed_photo(table, s3, uploader="user-alice")

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={}):
                response = h.lambda_handler(_build_event("photo-abc", "user-bob"), None)

        assert response["statusCode"] == 403
        body = json.loads(response["body"])
        assert "not authorised" in body["error"].lower()

    def test_photo_not_found_returns_404(self):
        """Returns 404 when photo_id does not exist in DynamoDB."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("delete_media")
            response = h.lambda_handler(_build_event("nonexistent-photo"), None)

        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert "not found" in body["error"].lower()

    def test_missing_photo_id_returns_400(self):
        """Returns 400 when photo_id path parameter is absent."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("delete_media")
            event = {"pathParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400

    def test_s3_object_deleted_after_successful_delete(self):
        """The S3 object is removed when a photo is successfully deleted."""
        s3_key = "uploads/user-alice/photo-abc_img.jpg"
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            _seed_photo(table, s3, s3_key=s3_key)

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={"DeletedFaces": ["face-001"]}):
                h.lambda_handler(_build_event("photo-abc", "user-alice"), None)

            # Object should no longer exist in S3
            objects = s3.list_objects_v2(Bucket=BUCKET_NAME).get("Contents", [])
            keys = [o["Key"] for o in objects]
            assert s3_key not in keys

    def test_dynamodb_records_deleted_after_successful_delete(self):
        """All DynamoDB records for the photo are removed on deletion."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            # Seed two face records for the same photo (multi-face scenario)
            _seed_photo(table, s3, face_id="face-001")
            table.put_item(Item={
                "photo_id": "photo-abc",
                "face_id": "face-002",
                "s3_key": "uploads/user-alice/photo-abc_img.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "user-alice",
                "content_type": "image/jpeg",
                "is_couple_photo": "false",
                "upload_timestamp": "2024-06-15T14:01:00+00:00",
            })

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={"DeletedFaces": ["face-001", "face-002"]}):
                h.lambda_handler(_build_event("photo-abc", "user-alice"), None)

            result = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("photo_id").eq("photo-abc")
            )
            assert result["Count"] == 0

    def test_no_face_record_skips_rekognition_delete(self):
        """Photos with NO_FACE records do not trigger Rekognition delete_faces."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            _seed_photo(table, s3, face_id="NO_FACE")

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={}) as mock_del:
                h.lambda_handler(_build_event("photo-abc", "user-alice"), None)

            mock_del.assert_not_called()

    def test_cors_headers_present(self):
        """Response always includes CORS headers."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("delete_media")
            response = h.lambda_handler(_build_event("nonexistent"), None)

        assert response["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_anonymous_user_cannot_delete(self):
        """Returns 403 when no Cognito claims are present (anonymous caller)."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)
            _seed_photo(table, s3, uploader="user-alice")

            h = load_handler("delete_media")
            with patch.object(h.rekognition, "delete_faces", return_value={}):
                event = {
                    "pathParameters": {"photo_id": "photo-abc"},
                    "requestContext": {},  # No authorizer claims
                }
                response = h.lambda_handler(event, None)

        assert response["statusCode"] == 403
