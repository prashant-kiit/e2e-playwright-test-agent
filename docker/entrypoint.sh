#!/usr/bin/env sh
# Apply DB migrations, then start the API. Keeps schema changes out of app code.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
