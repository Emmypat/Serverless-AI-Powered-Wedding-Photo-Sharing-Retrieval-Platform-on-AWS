# ── Lambda execution role ────────────────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_execution" {
  name               = "wedding-lambda-role-${var.stack_name}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

# Attach the AWS-managed basic execution policy (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline policy granting access to S3, DynamoDB and Rekognition
data "aws_iam_policy_document" "wedding_platform" {
  statement {
    sid    = "S3MediaAccess"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]

    resources = [
      aws_s3_bucket.media.arn,
      "${aws_s3_bucket.media.arn}/*",
    ]
  }

  statement {
    sid    = "DynamoDBAccess"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]

    resources = [
      aws_dynamodb_table.media_metadata.arn,
      "${aws_dynamodb_table.media_metadata.arn}/index/*",
    ]
  }

  statement {
    sid    = "RekognitionAccess"
    effect = "Allow"

    actions = [
      "rekognition:IndexFaces",
      "rekognition:SearchFacesByImage",
      "rekognition:SearchFaces",
      "rekognition:DeleteFaces",
      "rekognition:CreateCollection",
      "rekognition:DescribeCollection",
      "rekognition:DetectFaces",
      "rekognition:DetectLabels",
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "wedding_platform" {
  name   = "WeddingPlatformPolicy"
  role   = aws_iam_role.lambda_execution.id
  policy = data.aws_iam_policy_document.wedding_platform.json
}
