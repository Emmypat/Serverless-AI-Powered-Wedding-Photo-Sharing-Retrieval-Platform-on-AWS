resource "aws_dynamodb_table" "media_metadata" {
  name         = "wedding-media-metadata-${var.stack_name}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "photo_id"
  range_key    = "face_id"

  attribute {
    name = "photo_id"
    type = "S"
  }

  attribute {
    name = "face_id"
    type = "S"
  }

  attribute {
    name = "uploaded_by"
    type = "S"
  }

  attribute {
    name = "is_couple_photo"
    type = "S"
  }

  attribute {
    name = "upload_timestamp"
    type = "S"
  }

  global_secondary_index {
    name            = "face-id-index"
    hash_key        = "face_id"
    range_key       = "upload_timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "uploader-index"
    hash_key        = "uploaded_by"
    range_key       = "upload_timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "couple-photos-index"
    hash_key        = "is_couple_photo"
    range_key       = "upload_timestamp"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}
