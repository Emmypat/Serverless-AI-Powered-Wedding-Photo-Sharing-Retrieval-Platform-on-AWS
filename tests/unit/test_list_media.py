"""
Unit tests for the List Media Lambda function.
"""

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


class TestListMedia:

    def test_returns_all_media(self):
        """Returns all media items when no filter is applied."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)

            for photo_id, face_id, uploader in [
                ("photo-A", "face-1", "user-alice"),
                ("photo-B", "face-2", "user-bob"),
            ]:
                table.put_item(Item={
                    "photo_id": photo_id,
                    "face_id": face_id,
                    "s3_key": f"uploads/{uploader}/{photo_id}_img.jpg",
                    "bucket": BUCKET_NAME,
                    "uploaded_by": uploader,
                    "content_type": "image/jpeg",
                    "is_couple_photo": "false",
                    "upload_timestamp": "2024-06-15T12:00:00+00:00",
                })
                s3.put_object(Bucket=BUCKET_NAME, Key=f"uploads/{uploader}/{photo_id}_img.jpg", Body=b"img")

            h = load_handler("list_media")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 2

    def test_filter_by_uploader(self):
        """Returns only media uploaded by the specified user."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)

            for photo_id, face_id, uploader in [
                ("photo-A", "face-1", "user-alice"),
                ("photo-B", "face-2", "user-bob"),
            ]:
                table.put_item(Item={
                    "photo_id": photo_id,
                    "face_id": face_id,
                    "s3_key": f"uploads/{uploader}/{photo_id}_img.jpg",
                    "bucket": BUCKET_NAME,
                    "uploaded_by": uploader,
                    "content_type": "image/jpeg",
                    "is_couple_photo": "false",
                    "upload_timestamp": "2024-06-15T12:00:00+00:00",
                })
                s3.put_object(Bucket=BUCKET_NAME, Key=f"uploads/{uploader}/{photo_id}_img.jpg", Body=b"img")

            h = load_handler("list_media")
            event = {
                "queryStringParameters": {"uploaded_by": "user-alice"},
                "requestContext": {},
            }
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 1
        assert body["media"][0]["photo_id"] == "photo-A"
        assert body["media"][0]["uploaded_by"] == "user-alice"

    def test_media_includes_download_url(self):
        """Each returned media item includes a presigned download_url."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)

            table.put_item(Item={
                "photo_id": "photo-A",
                "face_id": "face-1",
                "s3_key": "uploads/user-alice/photo-A_img.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "user-alice",
                "content_type": "image/jpeg",
                "is_couple_photo": "false",
                "upload_timestamp": "2024-06-15T12:00:00+00:00",
            })
            s3.put_object(Bucket=BUCKET_NAME, Key="uploads/user-alice/photo-A_img.jpg", Body=b"img")

            h = load_handler("list_media")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        body = json.loads(response["body"])
        for item in body["media"]:
            assert item["download_url"] != ""

    def test_invalid_limit(self):
        """Returns 400 for non-integer limit parameter."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("list_media")
            event = {"queryStringParameters": {"limit": "xyz"}, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["statusCode"] == 400

    def test_is_couple_photo_field_is_bool(self):
        """The is_couple_photo field is returned as a boolean."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            table = _make_ddb_table(ddb)

            table.put_item(Item={
                "photo_id": "photo-A",
                "face_id": "face-1",
                "s3_key": "uploads/user-alice/photo-A_img.jpg",
                "bucket": BUCKET_NAME,
                "uploaded_by": "user-alice",
                "content_type": "image/jpeg",
                "is_couple_photo": "false",
                "upload_timestamp": "2024-06-15T12:00:00+00:00",
            })
            s3.put_object(Bucket=BUCKET_NAME, Key="uploads/user-alice/photo-A_img.jpg", Body=b"img")

            h = load_handler("list_media")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        body = json.loads(response["body"])
        for item in body["media"]:
            assert isinstance(item["is_couple_photo"], bool)

    def test_cors_headers_present(self):
        """Response includes CORS headers."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("list_media")
            event = {"queryStringParameters": None, "requestContext": {}}
            response = h.lambda_handler(event, None)

        assert response["headers"]["Access-Control-Allow-Origin"] == "*"
