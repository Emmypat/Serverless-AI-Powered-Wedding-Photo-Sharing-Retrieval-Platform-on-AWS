# ── REST API ─────────────────────────────────────────────────────────────────

resource "aws_api_gateway_rest_api" "wedding" {
  name        = "wedding-api-${var.stack_name}"
  description = "Wedding Photo Sharing & Retrieval API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# ── Cognito authorizer ────────────────────────────────────────────────────────

resource "aws_api_gateway_authorizer" "cognito" {
  name          = "CognitoAuthorizer"
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  type          = "COGNITO_USER_POOLS"
  provider_arns = [aws_cognito_user_pool.main.arn]

  identity_source = "method.request.header.Authorization"
}

# ─────────────────────────────────────────────────────────────────────────────
# Helper locals: Lambda invoke URIs
# ─────────────────────────────────────────────────────────────────────────────

locals {
  upload_handler_uri     = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.upload_handler.arn}/invocations"
  selfie_search_uri      = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.selfie_search.arn}/invocations"
  get_couple_photos_uri  = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.get_couple_photos.arn}/invocations"
  list_media_uri         = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.list_media.arn}/invocations"
  delete_media_uri       = "arn:aws:apigateway:${data.aws_region.current.name}:lambda:path/2015-03-31/functions/${aws_lambda_function.delete_media.arn}/invocations"

  cors_response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,PUT,DELETE,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# /upload-url   POST
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_api_gateway_resource" "upload_url" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  parent_id   = aws_api_gateway_rest_api.wedding.root_resource_id
  path_part   = "upload-url"
}

resource "aws_api_gateway_method" "upload_url_post" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.upload_url.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "upload_url_post" {
  rest_api_id             = aws_api_gateway_rest_api.wedding.id
  resource_id             = aws_api_gateway_resource.upload_url.id
  http_method             = aws_api_gateway_method.upload_url_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = local.upload_handler_uri
}

resource "aws_api_gateway_method" "upload_url_options" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.upload_url.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "upload_url_options" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.upload_url.id
  http_method = aws_api_gateway_method.upload_url_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "upload_url_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.upload_url.id
  http_method = aws_api_gateway_method.upload_url_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "upload_url_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.upload_url.id
  http_method = aws_api_gateway_method.upload_url_options.http_method
  status_code = "200"

  response_parameters = local.cors_response_parameters
  depends_on          = [aws_api_gateway_integration.upload_url_options]
}

# ─────────────────────────────────────────────────────────────────────────────
# /search   POST
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_api_gateway_resource" "search" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  parent_id   = aws_api_gateway_rest_api.wedding.root_resource_id
  path_part   = "search"
}

resource "aws_api_gateway_method" "search_post" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.search.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "search_post" {
  rest_api_id             = aws_api_gateway_rest_api.wedding.id
  resource_id             = aws_api_gateway_resource.search.id
  http_method             = aws_api_gateway_method.search_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = local.selfie_search_uri
}

resource "aws_api_gateway_method" "search_options" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.search.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "search_options" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.search.id
  http_method = aws_api_gateway_method.search_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "search_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.search.id
  http_method = aws_api_gateway_method.search_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "search_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.search.id
  http_method = aws_api_gateway_method.search_options.http_method
  status_code = "200"

  response_parameters = local.cors_response_parameters
  depends_on          = [aws_api_gateway_integration.search_options]
}

# ─────────────────────────────────────────────────────────────────────────────
# /couple-photos   GET
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_api_gateway_resource" "couple_photos" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  parent_id   = aws_api_gateway_rest_api.wedding.root_resource_id
  path_part   = "couple-photos"
}

resource "aws_api_gateway_method" "couple_photos_get" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.couple_photos.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "couple_photos_get" {
  rest_api_id             = aws_api_gateway_rest_api.wedding.id
  resource_id             = aws_api_gateway_resource.couple_photos.id
  http_method             = aws_api_gateway_method.couple_photos_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = local.get_couple_photos_uri
}

resource "aws_api_gateway_method" "couple_photos_options" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.couple_photos.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "couple_photos_options" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.couple_photos.id
  http_method = aws_api_gateway_method.couple_photos_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "couple_photos_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.couple_photos.id
  http_method = aws_api_gateway_method.couple_photos_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "couple_photos_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.couple_photos.id
  http_method = aws_api_gateway_method.couple_photos_options.http_method
  status_code = "200"

  response_parameters = local.cors_response_parameters
  depends_on          = [aws_api_gateway_integration.couple_photos_options]
}

# ─────────────────────────────────────────────────────────────────────────────
# /media   GET
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_api_gateway_resource" "media" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  parent_id   = aws_api_gateway_rest_api.wedding.root_resource_id
  path_part   = "media"
}

resource "aws_api_gateway_method" "media_get" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.media.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "media_get" {
  rest_api_id             = aws_api_gateway_rest_api.wedding.id
  resource_id             = aws_api_gateway_resource.media.id
  http_method             = aws_api_gateway_method.media_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = local.list_media_uri
}

resource "aws_api_gateway_method" "media_options" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.media.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "media_options" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media.id
  http_method = aws_api_gateway_method.media_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "media_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media.id
  http_method = aws_api_gateway_method.media_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "media_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media.id
  http_method = aws_api_gateway_method.media_options.http_method
  status_code = "200"

  response_parameters = local.cors_response_parameters
  depends_on          = [aws_api_gateway_integration.media_options]
}

# ─────────────────────────────────────────────────────────────────────────────
# /media/{photo_id}   DELETE
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_api_gateway_resource" "media_photo_id" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  parent_id   = aws_api_gateway_resource.media.id
  path_part   = "{photo_id}"
}

resource "aws_api_gateway_method" "media_delete" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.media_photo_id.id
  http_method   = "DELETE"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "media_delete" {
  rest_api_id             = aws_api_gateway_rest_api.wedding.id
  resource_id             = aws_api_gateway_resource.media_photo_id.id
  http_method             = aws_api_gateway_method.media_delete.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = local.delete_media_uri
}

resource "aws_api_gateway_method" "media_photo_id_options" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  resource_id   = aws_api_gateway_resource.media_photo_id.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "media_photo_id_options" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media_photo_id.id
  http_method = aws_api_gateway_method.media_photo_id_options.http_method
  type        = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "media_photo_id_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media_photo_id.id
  http_method = aws_api_gateway_method.media_photo_id_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

resource "aws_api_gateway_integration_response" "media_photo_id_options_200" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id
  resource_id = aws_api_gateway_resource.media_photo_id.id
  http_method = aws_api_gateway_method.media_photo_id_options.http_method
  status_code = "200"

  response_parameters = local.cors_response_parameters
  depends_on          = [aws_api_gateway_integration.media_photo_id_options]
}

# ── Deployment & Stage ────────────────────────────────────────────────────────

resource "aws_api_gateway_deployment" "wedding" {
  rest_api_id = aws_api_gateway_rest_api.wedding.id

  # Re-deploy whenever any method/integration changes
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.upload_url.id,
      aws_api_gateway_method.upload_url_post.id,
      aws_api_gateway_integration.upload_url_post.id,
      aws_api_gateway_resource.search.id,
      aws_api_gateway_method.search_post.id,
      aws_api_gateway_integration.search_post.id,
      aws_api_gateway_resource.couple_photos.id,
      aws_api_gateway_method.couple_photos_get.id,
      aws_api_gateway_integration.couple_photos_get.id,
      aws_api_gateway_resource.media.id,
      aws_api_gateway_method.media_get.id,
      aws_api_gateway_integration.media_get.id,
      aws_api_gateway_resource.media_photo_id.id,
      aws_api_gateway_method.media_delete.id,
      aws_api_gateway_integration.media_delete.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "wedding" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  deployment_id = aws_api_gateway_deployment.wedding.id
  stage_name    = var.environment

  # Enable detailed CloudWatch metrics for the stage
  variables = {
    environment = var.environment
  }
}

# ── Default 4XX / 5XX CORS gateway responses ─────────────────────────────────

resource "aws_api_gateway_gateway_response" "default_4xx" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  response_type = "DEFAULT_4XX"

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization'"
  }
}

resource "aws_api_gateway_gateway_response" "default_5xx" {
  rest_api_id   = aws_api_gateway_rest_api.wedding.id
  response_type = "DEFAULT_5XX"

  response_parameters = {
    "gatewayresponse.header.Access-Control-Allow-Origin"  = "'*'"
    "gatewayresponse.header.Access-Control-Allow-Headers" = "'Content-Type,Authorization'"
  }
}
