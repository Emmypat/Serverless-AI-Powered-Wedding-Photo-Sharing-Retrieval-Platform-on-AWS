locals {
  # Face collection ID matches the SAM template convention
  rekognition_collection_id = "wedding-faces-${var.stack_name}"

  # Environment variables shared by every Lambda function
  common_lambda_env = {
    MEDIA_BUCKET              = aws_s3_bucket.media.bucket
    METADATA_TABLE            = aws_dynamodb_table.media_metadata.name
    REKOGNITION_COLLECTION_ID = local.rekognition_collection_id
    LOG_LEVEL                 = "INFO"
    UPLOAD_URL_EXPIRY         = tostring(var.upload_url_expiry_seconds)
  }
}
