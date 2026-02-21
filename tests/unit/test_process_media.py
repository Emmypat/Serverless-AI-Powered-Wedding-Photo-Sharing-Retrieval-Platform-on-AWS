"""
Unit tests for the Process Media Lambda function.
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
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("MEDIA_BUCKET", BUCKET_NAME)
    monkeypatch.setenv("METADATA_TABLE", TABLE_NAME)
    monkeypatch.setenv("REKOGNITION_COLLECTION_ID", COLLECTION_ID)
    monkeypatch.setenv("COUPLE_FACE_IDS", "face-couple-1,face-couple-2")


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


def _make_s3_event(bucket: str, key: str) -> dict:
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                }
            }
        ]
    }


class TestProcessMedia:

    def test_processes_image_with_faces(self):
        """Indexes faces and writes DynamoDB metadata for an image with detected faces."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/abc123_photo.jpg",
                Body=b"fake-image-data",
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")

            mock_face_records = [
                {"Face": {"FaceId": "face-001"}},
                {"Face": {"FaceId": "face-002"}},
            ]
            with patch.object(h.rekognition, "index_faces", return_value={"FaceRecords": mock_face_records}):
                with patch.object(h.rekognition, "describe_collection", return_value={}):
                    event = _make_s3_event(BUCKET_NAME, "uploads/user-123/abc123_photo.jpg")
                    h.lambda_handler(event, None)

            table = ddb.Table(TABLE_NAME)
            result = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("photo_id").eq("abc123")
            )
            items = result["Items"]
            assert len(items) == 2
            face_ids_stored = {item["face_id"] for item in items}
            assert face_ids_stored == {"face-001", "face-002"}

    def test_processes_image_without_faces(self):
        """Writes a NO_FACE record for images with no detected faces."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/abc123_photo.jpg",
                Body=b"fake-image-data",
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")
            invalid_param_exc = h.rekognition.exceptions.InvalidParameterException(
                {"Error": {"Code": "InvalidParameterException", "Message": "No faces"}},
                "IndexFaces",
            )
            with patch.object(h.rekognition, "index_faces", side_effect=invalid_param_exc):
                with patch.object(h.rekognition, "describe_collection", return_value={}):
                    event = _make_s3_event(BUCKET_NAME, "uploads/user-123/abc123_photo.jpg")
                    h.lambda_handler(event, None)

            table = ddb.Table(TABLE_NAME)
            result = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("photo_id").eq("abc123")
            )
            items = result["Items"]
            assert len(items) == 1
            assert items[0]["face_id"] == "NO_FACE"

    def test_couple_photo_tagged(self):
        """Tags photo as couple photo when matched face ID is in COUPLE_FACE_IDS."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/abc123_photo.jpg",
                Body=b"fake-image-data",
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")
            # face-couple-1 is in COUPLE_FACE_IDS env var
            mock_face_records = [{"Face": {"FaceId": "face-couple-1"}}]
            with patch.object(h.rekognition, "index_faces", return_value={"FaceRecords": mock_face_records}):
                with patch.object(h.rekognition, "describe_collection", return_value={}):
                    event = _make_s3_event(BUCKET_NAME, "uploads/user-123/abc123_photo.jpg")
                    h.lambda_handler(event, None)

            table = ddb.Table(TABLE_NAME)
            result = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("photo_id").eq("abc123")
            )
            items = result["Items"]
            assert items[0]["is_couple_photo"] == "true"

    def test_non_couple_photo_not_tagged(self):
        """Does not tag photo as couple photo for non-couple faces."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/abc123_photo.jpg",
                Body=b"fake-image-data",
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")
            mock_face_records = [{"Face": {"FaceId": "face-guest-999"}}]
            with patch.object(h.rekognition, "index_faces", return_value={"FaceRecords": mock_face_records}):
                with patch.object(h.rekognition, "describe_collection", return_value={}):
                    event = _make_s3_event(BUCKET_NAME, "uploads/user-123/abc123_photo.jpg")
                    h.lambda_handler(event, None)

            table = ddb.Table(TABLE_NAME)
            result = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("photo_id").eq("abc123")
            )
            items = result["Items"]
            assert items[0]["is_couple_photo"] == "false"

    def test_collection_created_if_not_exists(self):
        """Creates the Rekognition collection when it does not exist."""
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=BUCKET_NAME)
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key="uploads/user-123/abc123_photo.jpg",
                Body=b"fake-image-data",
                ContentType="image/jpeg",
            )
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")
            not_found_exc = h.rekognition.exceptions.ResourceNotFoundException(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
                "DescribeCollection",
            )
            with patch.object(h.rekognition, "describe_collection", side_effect=not_found_exc):
                with patch.object(h.rekognition, "create_collection", return_value={}) as mock_create:
                    with patch.object(h.rekognition, "index_faces", return_value={"FaceRecords": []}):
                        event = _make_s3_event(BUCKET_NAME, "uploads/user-123/abc123_photo.jpg")
                        h.lambda_handler(event, None)

            mock_create.assert_called_once_with(CollectionId=COLLECTION_ID)

    def test_skips_record_with_missing_key(self):
        """Gracefully skips S3 event records that are missing bucket/key info."""
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET_NAME)
            ddb = boto3.resource("dynamodb", region_name="us-east-1")
            _make_ddb_table(ddb)

            h = load_handler("process_media")
            with patch.object(h.rekognition, "describe_collection", return_value={}):
                event = {"Records": [{"s3": {}}]}
                # Should not raise
                h.lambda_handler(event, None)
