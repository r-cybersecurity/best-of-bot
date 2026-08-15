#!/usr/bin/env bash
#
# deploy.sh — Build and deploy lambda_function.py to the Lambda function
# `twitter_bot__r_cybersecurity` using the AWS CLI.
#
# Responsibilities:
#   1. Build deploy_me.zip via build.sh
#   2. Update the deployed Lambda code (this NEVER reads or modifies the function
#      configuration, so credentials stored in environment variables are untouched)
#   3. Verify the deployment
#
# Credentials are retrieved from the named AWS CLI profile (stored in
# ~/.aws/credentials), so no secret material lives in this script.
#
# Usage: ./deploy.sh [<aws-profile>]   e.g. ./deploy.sh r-cybersecurity
# Defaults to the r-cybersecurity profile.
#
set -euo pipefail

AWS_PROFILE="${1:-r-cybersecurity}"
export AWS_PROFILE

REGION="us-west-2"
FUNC_NAME="twitter_bot__r_cybersecurity"
RUNTIME="python3.12"

echo "==> Using AWS CLI profile: $AWS_PROFILE"

# Step 1: build the deployment artifact
echo "==> Building deploy_me.zip"
bash ./build.sh

# Step 2: deploy the code ($LATEST; config and env vars are never touched)
ZIP_FILE="deploy_me.zip"
if [[ ! -f "$ZIP_FILE" ]]; then
    echo "ERROR: $ZIP_FILE not found after build." >&2
    exit 1
fi

echo "==> Deploying Lambda code for $FUNC_NAME ($REGION)"
# --publish omitted: keeps $LATEST, does not create/publish a new version.
# The code is uploaded FIRST (built for python3.12) so the packaged extensions
# match before we switch the runtime, avoiding any import-mismatch window.
aws lambda update-function-code \
    --function-name "$FUNC_NAME" \
    --region "$REGION" \
    --zip-file "fileb://$ZIP_FILE"

# Wait for the code update to finish before touching configuration (Lambda only
# allows one in-progress update at a time).
echo "==> Waiting for code update to complete..."
for _ in $(seq 1 40); do
    LU="$(aws lambda get-function-configuration \
        --function-name "$FUNC_NAME" \
        --region "$REGION" --query "LastUpdateStatus" --output text)"
    echo "   LastUpdateStatus=$LU"
    if [[ "$LU" == "Successful" ]]; then break; fi
    if [[ "$LU" == "Failed" ]]; then
        echo "ERROR: Lambda update failed." >&2
        exit 1
    fi
    sleep 3
done

echo "==> Updating Lambda runtime to $RUNTIME"
# Configuration only; environment variables are never modified.
aws lambda update-function-configuration \
    --function-name "$FUNC_NAME" \
    --region "$REGION" \
    --runtime "$RUNTIME"

# Step 3: verify (configuration only; environment variables are not read)
echo "==> Verifying deployment"

echo "==> Function Summary (latest configuration)"
aws lambda get-function-configuration \
    --function-name "$FUNC_NAME" \
    --region "$REGION" \
    --query "[FunctionArn, State, LastUpdateStatus, Runtime, Handler]" \
    --output text

echo "DONE"
