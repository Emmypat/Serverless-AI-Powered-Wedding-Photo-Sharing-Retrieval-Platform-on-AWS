/**
 * Wedding Platform – Runtime Configuration
 *
 * This file is generated/updated at deploy time by the CI/CD pipeline or the
 * `make deploy-frontend` Makefile target.  It injects the stack outputs as
 * global window variables so that app.js can pick them up without needing a
 * build step.
 *
 * DO NOT commit real values for production deployments.
 * The placeholders below are replaced by the deploy script:
 *
 *   sed -i \
 *     "s|YOUR_API_GATEWAY_URL/dev|${API_URL}|g;
 *      s|us-east-1_EXAMPLE|${USER_POOL_ID}|g;
 *      s|EXAMPLE_CLIENT_ID|${USER_POOL_CLIENT}|g;
 *      s|AWS_REGION_PLACEHOLDER|${REGION}|g" \
 *     frontend/js/config.js
 *
 * For local development against `sam local start-api`, override the values
 * directly here (the file is gitignored via the *.local.js pattern if you
 * prefer to keep a separate local copy).
 */

window.WEDDING_API_ENDPOINT    = 'https://YOUR_API_GATEWAY_URL/dev';
window.WEDDING_USER_POOL_ID    = 'us-east-1_EXAMPLE';
window.WEDDING_USER_POOL_CLIENT = 'EXAMPLE_CLIENT_ID';
window.WEDDING_AWS_REGION      = 'AWS_REGION_PLACEHOLDER';
