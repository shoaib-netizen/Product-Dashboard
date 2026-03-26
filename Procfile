# Procfile for Render/Heroku deployment
# Use ONE of these depending on your deployment needs:

# Web server (for API endpoints and manual triggers)
web: gunicorn "main:create_flask_app()" --bind 0.0.0.0:$PORT

# Background worker (for scheduled email processing)
worker: python scheduler.py
