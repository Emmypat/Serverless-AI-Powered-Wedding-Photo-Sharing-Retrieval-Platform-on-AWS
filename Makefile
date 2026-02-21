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
deploy-frontend: ## Inject config, sync the frontend to S3, and invalidate CloudFront
	@API_URL=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text); \
	FRONTEND_BUCKET=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text); \
	USER_POOL_ID=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text); \
	USER_POOL_CLIENT=$$(aws cloudformation describe-stacks --stack-name $(STACK_NAME) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text); \
	TMPFILE=$$(mktemp); \
	cp frontend/js/config.js "$$TMPFILE"; \
	trap 'cp "$$TMPFILE" frontend/js/config.js; rm -f "$$TMPFILE"' EXIT INT TERM; \
	perl -i -pe "s|https://YOUR_API_GATEWAY_URL/dev|$$API_URL|g; \
	   s|us-east-1_EXAMPLE|$$USER_POOL_ID|g; \
	   s|EXAMPLE_CLIENT_ID|$$USER_POOL_CLIENT|g; \
	   s|AWS_REGION_PLACEHOLDER|$(REGION)|g" \
	  frontend/js/config.js; \
	echo "Deploying frontend to s3://$$FRONTEND_BUCKET"; \
	aws s3 sync frontend/ s3://$$FRONTEND_BUCKET/ --delete || { echo "ERROR: S3 sync failed"; exit 1; }; \
	DIST_ID=$$(aws cloudfront list-distributions \
	  --query "DistributionList.Items[?contains(Origins.Items[0].DomainName,'$$FRONTEND_BUCKET')].Id" \
	  --output text 2>/dev/null); \
	if [ -n "$$DIST_ID" ]; then \
	  aws cloudfront create-invalidation --distribution-id $$DIST_ID --paths "/*" > /dev/null; \
	  echo "CloudFront cache invalidated ($$DIST_ID)"; \
	fi

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
