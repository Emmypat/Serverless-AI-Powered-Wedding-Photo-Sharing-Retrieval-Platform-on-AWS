# ── Package each Lambda handler directory into a zip file ────────────────────

data "archive_file" "upload_handler" {
  type        = "zip"
  source_dir  = "${path.module}/../src/upload_handler"
  output_path = "${path.module}/.lambda_builds/upload_handler.zip"
}

data "archive_file" "process_media" {
  type        = "zip"
  source_dir  = "${path.module}/../src/process_media"
  output_path = "${path.module}/.lambda_builds/process_media.zip"
}

data "archive_file" "selfie_search" {
  type        = "zip"
  source_dir  = "${path.module}/../src/selfie_search"
  output_path = "${path.module}/.lambda_builds/selfie_search.zip"
}

data "archive_file" "get_couple_photos" {
  type        = "zip"
  source_dir  = "${path.module}/../src/get_couple_photos"
  output_path = "${path.module}/.lambda_builds/get_couple_photos.zip"
}

data "archive_file" "list_media" {
  type        = "zip"
  source_dir  = "${path.module}/../src/list_media"
  output_path = "${path.module}/.lambda_builds/list_media.zip"
}

data "archive_file" "delete_media" {
  type        = "zip"
  source_dir  = "${path.module}/../src/delete_media"
  output_path = "${path.module}/.lambda_builds/delete_media.zip"
}

# ── Lambda functions ─────────────────────────────────────────────────────────

resource "aws_lambda_function" "upload_handler" {
  function_name    = "wedding-upload-handler-${var.stack_name}"
  description      = "Generates presigned S3 URLs for direct client-side media uploads"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.upload_handler.output_path
  source_code_hash = data.archive_file.upload_handler.output_base64sha256

  environment {
    variables = local.common_lambda_env
  }
}

resource "aws_lambda_function" "process_media" {
  function_name    = "wedding-process-media-${var.stack_name}"
  description      = "S3-triggered; indexes faces via Rekognition and stores metadata in DynamoDB"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 60
  memory_size      = 512
  filename         = data.archive_file.process_media.output_path
  source_code_hash = data.archive_file.process_media.output_base64sha256

  environment {
    variables = merge(local.common_lambda_env, {
      COUPLE_FACE_IDS = var.couple_face_ids
    })
  }
}

resource "aws_lambda_function" "selfie_search" {
  function_name    = "wedding-selfie-search-${var.stack_name}"
  description      = "Accepts a selfie image and returns presigned URLs for matching wedding photos"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.selfie_search.output_path
  source_code_hash = data.archive_file.selfie_search.output_base64sha256

  environment {
    variables = local.common_lambda_env
  }
}

resource "aws_lambda_function" "get_couple_photos" {
  function_name    = "wedding-get-couple-photos-${var.stack_name}"
  description      = "Returns presigned URLs for all curated couple photos"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.get_couple_photos.output_path
  source_code_hash = data.archive_file.get_couple_photos.output_base64sha256

  environment {
    variables = local.common_lambda_env
  }
}

resource "aws_lambda_function" "list_media" {
  function_name    = "wedding-list-media-${var.stack_name}"
  description      = "Lists all wedding media with presigned download URLs"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.list_media.output_path
  source_code_hash = data.archive_file.list_media.output_base64sha256

  environment {
    variables = local.common_lambda_env
  }
}

resource "aws_lambda_function" "delete_media" {
  function_name    = "wedding-delete-media-${var.stack_name}"
  description      = "Deletes a photo from S3 and its metadata from DynamoDB"
  role             = aws_iam_role.lambda_execution.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  timeout          = 30
  memory_size      = 256
  filename         = data.archive_file.delete_media.output_path
  source_code_hash = data.archive_file.delete_media.output_base64sha256

  environment {
    variables = local.common_lambda_env
  }
}

# ── Allow S3 to invoke the process_media function ────────────────────────────

resource "aws_lambda_permission" "process_media_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.process_media.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.media.arn
  source_account = data.aws_caller_identity.current.account_id
}

# ── Allow API Gateway to invoke each API-exposed function ─────────────────────

resource "aws_lambda_permission" "upload_handler_apigw" {
  statement_id   = "AllowAPIGatewayInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.upload_handler.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_api_gateway_rest_api.wedding.execution_arn}/*/*"
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "selfie_search_apigw" {
  statement_id   = "AllowAPIGatewayInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.selfie_search.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_api_gateway_rest_api.wedding.execution_arn}/*/*"
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "get_couple_photos_apigw" {
  statement_id   = "AllowAPIGatewayInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.get_couple_photos.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_api_gateway_rest_api.wedding.execution_arn}/*/*"
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "list_media_apigw" {
  statement_id   = "AllowAPIGatewayInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.list_media.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_api_gateway_rest_api.wedding.execution_arn}/*/*"
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "delete_media_apigw" {
  statement_id   = "AllowAPIGatewayInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.delete_media.function_name
  principal      = "apigateway.amazonaws.com"
  source_arn     = "${aws_api_gateway_rest_api.wedding.execution_arn}/*/*"
  source_account = data.aws_caller_identity.current.account_id
}
