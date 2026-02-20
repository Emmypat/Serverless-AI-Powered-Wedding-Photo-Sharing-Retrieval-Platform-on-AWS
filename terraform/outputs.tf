output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = "https://${aws_api_gateway_rest_api.wedding.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.environment}"
}

output "cloudfront_url" {
  description = "CloudFront URL for the wedding platform frontend"
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "media_bucket_name" {
  description = "S3 bucket for storing wedding media"
  value       = aws_s3_bucket.media.bucket
}

output "frontend_bucket_name" {
  description = "S3 bucket for hosting the frontend SPA"
  value       = aws_s3_bucket.frontend.bucket
}

output "user_pool_id" {
  description = "Cognito User Pool ID"
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_client_id" {
  description = "Cognito User Pool App Client ID"
  value       = aws_cognito_user_pool_client.app.id
}

output "metadata_table_name" {
  description = "DynamoDB table for media metadata"
  value       = aws_dynamodb_table.media_metadata.name
}

output "rekognition_collection_id" {
  description = "Amazon Rekognition face collection ID"
  value       = aws_rekognition_collection.wedding_faces.id
}
