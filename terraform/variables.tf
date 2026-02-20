variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region to deploy into."
}

variable "stack_name" {
  type        = string
  default     = "wedding-platform"
  description = "Unique name for this deployment. Used to namespace all resource names."
}

variable "environment" {
  type        = string
  default     = "dev"
  description = "Deployment environment (dev | staging | prod)."

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "couple_face_ids" {
  type        = string
  default     = ""
  description = "Comma-separated Amazon Rekognition FaceIds belonging to the couple. Leave empty until faces are enrolled."
}

variable "upload_url_expiry_seconds" {
  type        = number
  default     = 3600
  description = "Lifetime (in seconds) of presigned S3 upload URLs."
}
