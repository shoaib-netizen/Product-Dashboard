"""
Flask Web Application - Email Dashboard
Displays email tracking data from Google Sheets in a beautiful table interface.
Includes /process endpoint for n8n or external cron triggers.
Chat scheduler runs automatically in background thread on startup.
"""
from flask import Flask, jsonify, request
from src.services.sheets_service import GoogleSheetsService
from config import Config
import os
import threading
import time
import schedule
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Lazy-initialized Google Sheets Service (avoids heavy API calls on every worker startup)
_sheets_service = None

def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
    return _sheets_service

# Track email processing state to prevent overlapping runs
_processing_lock = threading.Lock()
_is_processing = False
_last_run = None
_last_result = None

# Track chat scheduler state
_chat_last_run = None
_chat_last_result = None


# ─────────────────────────────────────────────
# EMAIL PROCESSING (triggered by n8n)
# ─────────────────────────────────────────────

_email_agent = None

def _run_email_processing():
    """Background thread that does the actual email processing."""
    global _is_processing, _last_run, _last_result, _email_agent
    try:
        if _email_agent is None:
            from main import EmailToSheetsAgent
            _email_agent = EmailToSheetsAgent()
        count = _email_agent.process_emails()
        _last_run = datetime.utcnow()
        _last_result = {'processed': count, 'status': 'success'}
        print(f"[Email] Completed. Processed {count} emails at {_last_run.isoformat()}")
    except Exception as e:
        _last_run = datetime.utcnow()
        _last_result = {'error': str(e), 'status': 'failed'}
        print(f"[Email] Failed: {e}")
    finally:
        _is_processing = False
        _processing_lock.release()


# ─────────────────────────────────────────────
# CHAT PROCESSING (self-timed, runs automatically)
# ─────────────────────────────────────────────

_chat_agent = None

def _chat_job():
    """Single chat processing run — fetches new G Chat messages and writes to sheet."""
    global _chat_last_run, _chat_last_result, _chat_agent
    print(f"[Chat] Running check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    try:
        if _chat_agent is None:
            from src.agents import ChatToSheetsAgent
            _chat_agent = ChatToSheetsAgent()
        count = _chat_agent.process_messages()
        _chat_last_run = datetime.utcnow()
        _chat_last_result = {'inserted': count, 'status': 'success'}
        print(f"[Chat] Done. Inserted {count} new message(s).")
    except Exception as e:
        _chat_last_run = datetime.utcnow()
        _chat_last_result = {'error': str(e), 'status': 'failed'}
        print(f"[Chat] Failed: {e}")


def _start_chat_scheduler():
    """
    Runs in a daemon thread forever.
    Calls _chat_job() immediately on startup, then every N minutes.
    Uses CHAT_CHECK_INTERVAL_MINUTES from config (default: 5).
    If CHAT_SPACE_ID is not set, chat scheduler is silently disabled.
    """
    if not Config.CHAT_SPACE_ID:
        print("[Chat] CHAT_SPACE_ID not set — chat scheduler disabled.")
        return

    interval = Config.CHAT_CHECK_INTERVAL_MINUTES
    print(f"[Chat] Scheduler started. Space: {Config.CHAT_SPACE_ID} | Interval: {interval} min(s).")

    # Run once immediately on startup
    _chat_job()

    # Then schedule every N minutes
    schedule.every(interval).minutes.do(_chat_job)

    while True:
        schedule.run_pending()
        time.sleep(30)


# Start chat scheduler as a daemon thread when the app loads
# daemon=True means it will automatically stop if the main process stops
_chat_thread = threading.Thread(target=_start_chat_scheduler, daemon=True, name="chat-scheduler")
_chat_thread.start()


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    """Status page."""
    return jsonify({
        'service': 'Email + Chat to Sheets Agent',
        'status': 'running',
        'version': '1.0.0',
        'endpoints': {
            '/health': 'Health check',
            '/process': 'Trigger email processing (POST)',
            '/api/emails': 'Get all emails',
            '/api/stats': 'Get statistics'
        }
    })


@app.route('/health')
def health():
    """Health check endpoint — shows status of both email and chat."""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'email': {
            'processing': _is_processing,
            'last_run': _last_run.isoformat() if _last_run else None,
            'last_result': _last_result
        },
        'chat': {
            'enabled': bool(Config.CHAT_SPACE_ID),
            'last_run': _chat_last_run.isoformat() if _chat_last_run else None,
            'last_result': _chat_last_result
        }
    })


@app.route('/process', methods=['POST', 'GET'])
def process_emails():
    """
    Trigger email processing. Called by n8n Schedule Trigger → HTTP Request.
    Starts processing in background thread and returns immediately.
    Returns 429 if already processing.
    """
    global _is_processing

    if not _processing_lock.acquire(blocking=False):
        return jsonify({
            'success': False,
            'message': 'Processing already in progress',
            'last_run': _last_run.isoformat() if _last_run else None
        }), 429

    _is_processing = True
    thread = threading.Thread(target=_run_email_processing, daemon=True)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Processing started in background',
        'timestamp': datetime.utcnow().isoformat(),
        'check_status': '/health'
    })


# Simple in-memory cache for sheet data (60 second TTL)
_data_cache = {'data': None, 'timestamp': 0}
CACHE_TTL = 60  # seconds

def get_cached_data():
    if time.time() - _data_cache['timestamp'] > CACHE_TTL:
        _data_cache['data'] = get_sheets_service().get_all_data()
        _data_cache['timestamp'] = time.time()
    return _data_cache['data']


@app.route('/api/emails')
def get_emails():
    """API endpoint to fetch all emails data."""
    try:
        data = get_cached_data()
        return jsonify({
            'success': True,
            'data': data,
            'count': len(data)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/stats')
def get_stats():
    """API endpoint to fetch statistics."""
    try:
        data = get_cached_data()

        total_emails = len(data)
        replied_emails = len([d for d in data if d.get('Reply Status') == 'Replied'])
        pending_emails = total_emails - replied_emails
        senders = set(d.get('Sender Email', '') for d in data if d.get('Sender Email'))

        return jsonify({
            'success': True,
            'stats': {
                'total': total_emails,
                'replied': replied_emails,
                'pending': pending_emails,
                'unique_senders': len(senders)
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)