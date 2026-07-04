# Deploying InterviewCraft to Google Cloud Platform

The app deploys as two Cloud Run services (backend + frontend) with Firestore as the
database. Total one-time setup is ~15 minutes; each deploy after that is one command.

## One-time GCP setup

1. **Project & APIs**
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
       artifactregistry.googleapis.com firestore.googleapis.com secretmanager.googleapis.com
   ```

2. **Firestore** — create a database in native mode:
   ```bash
   gcloud firestore databases create --location=us-central1
   ```
   On Cloud Run the backend uses the service's default credentials automatically —
   no service-account key file needed in production.

3. **Secrets** — store the sensitive env values in Secret Manager:
   ```bash
   printf '%s' "$(openssl rand -hex 32)" | gcloud secrets create ic-session-jwt-secret --data-file=-
   printf '%s' "sk-..."                  | gcloud secrets create ic-openai-api-key --data-file=-
   printf '%s' "xxxx.apps.googleusercontent.com" | gcloud secrets create ic-google-oauth-client-id --data-file=-
   ```
   Grant the Cloud Run runtime service account `roles/secretmanager.secretAccessor` and
   `roles/datastore.user`.

4. **Google OAuth client** — in [Google Cloud Console → APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials),
   create an OAuth 2.0 Client ID (Web application). After the first frontend deploy, add
   the frontend's Cloud Run URL to **Authorized JavaScript origins**.

## Deploy

```bash
export NEXT_PUBLIC_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
./deploy/deploy.sh YOUR_PROJECT_ID us-central1
```

This deploys the backend (from source via Cloud Build), builds the frontend image with the
backend URL baked in, deploys it, and wires backend CORS to the frontend URL.

Subsequent deploys: rerun the same command, or `./deploy/deploy.sh <project> <region> backend`
/ `frontend` for one side only.

## Notes

- Cloud Run supports WebSockets natively; the backend sets `--timeout 3600` so long agent
  runs and WS connections aren't cut off.
- Cost stays near zero at idle (`--min-instances 0`). For instant cold starts set
  `--min-instances 1` on the backend.
- Extra provider keys (Gemini, Tavily, Google CSE) can be added the same way:
  create a secret, then `gcloud run services update interviewcraft-backend --set-secrets ...`.
