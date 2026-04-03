# Procfile for Render deployment
# Web server with /process endpoint (triggered by n8n every 5 mins)
web: gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --threads 4 --max-requests 500 --max-requests-jitter 50