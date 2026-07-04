#!/usr/bin/env bash
# InterviewCraft — one-command deploy to Google Cloud Run.
#
# Prereqs (one-time, see deploy/README.md for detail):
#   gcloud auth login
#   gcloud config set project <PROJECT_ID>
#   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
#       artifactregistry.googleapis.com firestore.googleapis.com
#   Create Firestore database (native mode) + secrets in Secret Manager.
#
# Usage:
#   ./deploy/deploy.sh <PROJECT_ID> <REGION>            # deploys backend then frontend
#   ./deploy/deploy.sh <PROJECT_ID> <REGION> backend    # backend only
#   ./deploy/deploy.sh <PROJECT_ID> <REGION> frontend   # frontend only
set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh <PROJECT_ID> <REGION> [backend|frontend]}"
REGION="${2:?Usage: deploy.sh <PROJECT_ID> <REGION> [backend|frontend]}"
TARGET="${3:-all}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

deploy_backend() {
  echo "==> Deploying backend to Cloud Run..."
  gcloud run deploy interviewcraft-backend \
    --project "$PROJECT_ID" --region "$REGION" \
    --source "$ROOT/backend" \
    --allow-unauthenticated \
    --port 8000 \
    --memory 1Gi --cpu 1 --min-instances 0 --max-instances 4 \
    --timeout 3600 \
    --set-env-vars "APP_ENV=production,FIREBASE_PROJECT_ID=$PROJECT_ID" \
    --set-secrets "SESSION_JWT_SECRET=ic-session-jwt-secret:latest,OPENAI_API_KEY=ic-openai-api-key:latest,GOOGLE_OAUTH_CLIENT_ID=ic-google-oauth-client-id:latest"
  BACKEND_URL=$(gcloud run services describe interviewcraft-backend \
    --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')
  echo "Backend: $BACKEND_URL"
  echo "NOTE: set FRONTEND_ORIGIN on the backend after the frontend deploy:"
  echo "  gcloud run services update interviewcraft-backend --region $REGION --update-env-vars FRONTEND_ORIGIN=<frontend-url>"
}

deploy_frontend() {
  echo "==> Deploying frontend to Cloud Run..."
  BACKEND_URL=$(gcloud run services describe interviewcraft-backend \
    --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)' 2>/dev/null || true)
  if [[ -z "$BACKEND_URL" ]]; then
    echo "ERROR: deploy the backend first (frontend needs its URL at build time)." >&2
    exit 1
  fi
  WS_URL="${BACKEND_URL/https:/wss:}"
  : "${NEXT_PUBLIC_GOOGLE_CLIENT_ID:?Export NEXT_PUBLIC_GOOGLE_CLIENT_ID before deploying the frontend}"
  gcloud builds submit "$ROOT/frontend" \
    --project "$PROJECT_ID" \
    --tag "$REGION-docker.pkg.dev/$PROJECT_ID/interviewcraft/frontend:latest" 2>/dev/null || {
      echo "Artifact Registry repo missing — creating it..."
      gcloud artifacts repositories create interviewcraft \
        --project "$PROJECT_ID" --location "$REGION" --repository-format docker
    }
  gcloud builds submit "$ROOT/frontend" \
    --project "$PROJECT_ID" \
    --config "$ROOT/deploy/cloudbuild-frontend.yaml" \
    --substitutions "_REGION=$REGION,_API_URL=$BACKEND_URL,_WS_URL=$WS_URL,_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID"
  gcloud run deploy interviewcraft-frontend \
    --project "$PROJECT_ID" --region "$REGION" \
    --image "$REGION-docker.pkg.dev/$PROJECT_ID/interviewcraft/frontend:latest" \
    --allow-unauthenticated --port 3000 \
    --memory 512Mi --min-instances 0 --max-instances 4
  FRONTEND_URL=$(gcloud run services describe interviewcraft-frontend \
    --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')
  echo "Frontend: $FRONTEND_URL"
  echo "==> Pointing backend CORS at the frontend..."
  gcloud run services update interviewcraft-backend \
    --project "$PROJECT_ID" --region "$REGION" \
    --update-env-vars "FRONTEND_ORIGIN=$FRONTEND_URL"
  echo "Done. Add $FRONTEND_URL to your Google OAuth client's authorized JavaScript origins."
}

case "$TARGET" in
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  all)      deploy_backend; deploy_frontend ;;
  *)        echo "Unknown target: $TARGET" >&2; exit 1 ;;
esac
