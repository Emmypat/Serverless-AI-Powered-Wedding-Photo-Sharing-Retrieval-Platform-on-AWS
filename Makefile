.PHONY: install test lint build deploy clean help

# ── Variables ──────────────────────────────────────────────────────────────────
STACK_NAME    ?= wedding-platform
REGION        ?= us-east-1
ENVIRONMENT   ?= dev
PYTHON        ?= python3

# ── Help ───────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Local development ──────────────────────────────────────────────────────────
install: ## Install all local development dependencies
	pip install -r requirements.txt

test: ## Run unit tests with coverage
	pytest tests/unit/ -v \
	  --cov=src \
	  --cov-report=term-missing

test-ci: ## Run unit tests in CI mode (no coverage display, produce XML report)
	pytest tests/unit/ -v \
	  --cov=src \
	  --cov-report=xml:coverage.xml

lint: ## Lint source code with flake8
	flake8 src/ --max-line-length=120 --extend-ignore=E501

# ── AWS SAM ────────────────────────────────────────────────────────────────────
build: ## Build Lambda packages with SAM
	sam build --parallel

validate: ## Validate the SAM / CloudFormation template
	sam validate --lint

local-api: build ## Start a local API Gateway for development testing
	sam local start-api \
	  --parameter-overrides \
	    Environment=$(ENVIRONMENT) \
	    CoupleFaceIds=""

deploy: build ## Build and deploy the stack to AWS
	sam deploy \
	  --stack-name $(STACK_NAME) \
	  --region $(REGION) \
	  --parameter-overrides \
	    Environment=$(ENVIRONMENT) \
	  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
	  --resolve-s3

deploy-guided: build ## Guided first-time deploy (interactive)
	sam deploy --guided

# ── Frontend ───────────────────────────────────────────────────────────────────
deploy-frontend: ## Sync the frontend to the S3 frontend bucket
	@FRONTEND_BUCKET=$$(aws cloudformation describe-stacks \
	  --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" \
	  --output text); \
	echo "Deploying frontend to s3://$$FRONTEND_BUCKET"; \
	aws s3 sync frontend/ s3://$$FRONTEND_BUCKET/ --delete

# ── Clean-up ───────────────────────────────────────────────────────────────────
clean: ## Remove SAM build artefacts and Python cache
	rm -rf .aws-sam __pycache__ .pytest_cache coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

destroy: ## DELETE the CloudFormation stack (IRREVERSIBLE)
	@echo "WARNING: This will permanently delete the $(STACK_NAME) stack and all its resources."
	@read -p "Type the stack name to confirm: " confirm; \
	  [ "$$confirm" = "$(STACK_NAME)" ] || (echo "Aborted." && exit 1)
	aws s3 rm s3://$$(aws cloudformation describe-stacks \
	  --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='MediaBucketName'].OutputValue" \
	  --output text) --recursive 2>/dev/null || true
	sam delete --stack-name $(STACK_NAME) --region $(REGION) --no-prompts
