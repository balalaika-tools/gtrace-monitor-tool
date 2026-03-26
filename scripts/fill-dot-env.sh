#!/bin/bash
set -e

ROLE_ARN="arn:aws:iam::340251341495:role/PepStack-CrossAccountRole55335AA5-aavd1MCWHTfI"
SESSION_NAME="AiExceptionSess"
PROFILE="gresham"
ENV_FILE=".env"

CREDS=$(aws sts assume-role --role-arn "$ROLE_ARN" --role-session-name "$SESSION_NAME" --profile "$PROFILE" --output json)

ACCESS_KEY=$(echo "$CREDS" | jq -r '.Credentials.AccessKeyId')
SECRET_KEY=$(echo "$CREDS" | jq -r '.Credentials.SecretAccessKey')
SESSION_TOKEN=$(echo "$CREDS" | jq -r '.Credentials.SessionToken')
EXPIRATION=$(echo "$CREDS" | jq -r '.Credentials.Expiration')

# Create .env if it doesn't exist
touch "$ENV_FILE"

# Remove any existing AWS credential lines to avoid duplicates
sed -i '' '/^AWS_ACCESS_KEY_ID=/d;/^AWS_SECRET_ACCESS_KEY=/d;/^AWS_SESSION_TOKEN=/d;/^AWS_DEFAULT_REGION=/d' "$ENV_FILE"

# Append fresh credentials
echo "AWS_ACCESS_KEY_ID=$ACCESS_KEY" >> "$ENV_FILE"
echo "AWS_SECRET_ACCESS_KEY=$SECRET_KEY" >> "$ENV_FILE"
echo "AWS_SESSION_TOKEN=$SESSION_TOKEN" >> "$ENV_FILE"
echo "AWS_DEFAULT_REGION=us-east-1" >> "$ENV_FILE"

echo "✓ Credentials written to $ENV_FILE (expire: $EXPIRATION)"
