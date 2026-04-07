"""
Flask Web Application - Email Dashboard
Displays email tracking data from Google Sheets in a beautiful table interface.
Includes /process endpoint for n8n or external cron triggers.
Chat scheduler runs automatically in background thread on startup.

FIXES APPLIED:
- Replaced threading.Lock with a simple boolean flag (no deadlock possible)
- Added /reset endpoint to manually unstick processing state
- Added /process?force=true to force a new run even if stuck
- Errors from background thread now fully printed with traceback
- Added lock timeout safety: auto-resets if processing > 10 minutes
"""
from flask import Flask, jsonify, request
from src.services.sheets_service import GoogleSheetsService
from config import Config
import os
import threading
import time
import traceback
import schedule
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Lazy-initialized Google Sheets Service
_sheets_service = None

def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
    return _sheets_service

# ─────────────────────────────────────────────
# EMAIL PROCESSING STATE
# Using a simple boolean + timestamp instead of threading.Lock
# Lock-based approach caused permanent deadlock when thread crashed
# ─────────────────────────────────────────────
_is_processing = False
_processing_started_at = None  # Track when processing started (for timeout safety)
_last_run = None
_last_result = None

MAX_PROCESSING_MINUTES = 10  # Auto-reset if stuck longer than this


def _is_stuck():
    """Check if processing flag has been True for too long (crashed thread)."""
    if not _is_processing or _processing_started_at is None:
        return False
    elapsed = datetime.utcnow() - _processing_started_at
    return elapsed > timedelta(minutes=MAX_PROCESSING_MINUTES)


_email_agent = None

def _run_email_processing():
    """Background thread that does the actual email processing."""
    global _is_processing, _processing_started_at, _last_run, _last_result, _email_agent
    try:
        print(f"[Email] Starting email processing at {datetime.utcnow().isoformat()}")
        if _email_agent is None:
            print("[Email] Initializing EmailToSheetsAgent...")
            from main import EmailToSheetsAgent
            _email_agent = EmailToSheetsAgent()
            print("[Email] Agent initialized successfully")
        count = _email_agent.process_emails()
        _last_run = datetime.utcnow()
        _last_result = {'processed': count, 'status': 'success'}
        print(f"[Email] Completed. Processed {count} emails at {_last_run.isoformat()}")
    except Exception as e:
        
        _last_result = {'error': str(e), 'status': 'failed'}
        print(f"[Email] FAILED with exception: {e}")
        print(traceback.format_exc())  # Full traceback to Render logs
        if 'credentials' in str(e).lower() or 'token' in str(e).lower():
         _email_agent = None  # Reset agent so next run re-initializes cleanly
    finally:
        # Always reset the flag — no lock that can get stuck
        _is_processing = False
        _processing_started_at = None
        print("[Email] Processing flag released")


# ─────────────────────────────────────────────
# CHAT PROCESSING
# ─────────────────────────────────────────────
_chat_last_run = None
_chat_last_result = None
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
        print(traceback.format_exc())
        _chat_agent = None  # Reset so next run re-initializes


def _start_chat_scheduler():
    """
    Runs in a daemon thread forever.
    Calls _chat_job() immediately on startup, then every N minutes.
    """
    if not Config.CHAT_SPACE_ID:
        print("[Chat] CHAT_SPACE_ID not set — chat scheduler disabled.")
        return

    interval = Config.CHAT_CHECK_INTERVAL_MINUTES
    print(f"[Chat] Scheduler started. Space: {Config.CHAT_SPACE_ID} | Interval: {interval} min(s).")

    _chat_job()

    schedule.every(interval).minutes.do(_chat_job)

    while True:
        schedule.run_pending()
        time.sleep(30)


_chat_thread = threading.Thread(target=_start_chat_scheduler, daemon=True, name="chat-scheduler")
_chat_thread.start()


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return jsonify({
        'service': 'Email + Chat to Sheets Agent',
        'status': 'running',
        'version': '1.1.0',
        'endpoints': {
            '/health': 'Health check',
            '/process': 'Trigger email processing (POST or GET)',
            '/process?force=true': 'Force trigger even if stuck',
            '/reset': 'Reset stuck processing state (POST)',
            '/api/emails': 'Get all emails',
            '/api/stats': 'Get statistics'
        }
    })


@app.route('/health')
def health():
    """Health check — shows full status including last error."""
    stuck = _is_stuck()
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'email': {
            'processing': _is_processing,
            'processing_stuck': stuck,
            'processing_started_at': _processing_started_at.isoformat() if _processing_started_at else None,
            'last_run': _last_run.isoformat() if _last_run else None,
            'last_result': _last_result
        },
        'chat': {
            'enabled': bool(Config.CHAT_SPACE_ID),
            'last_run': _chat_last_run.isoformat() if _chat_last_run else None,
            'last_result': _chat_last_result
        }
    })


@app.route('/reset', methods=['POST', 'GET'])
def reset_processing():
    """
    Manually reset stuck processing state.
    Call this if /health shows processing=true but it's clearly not running.
    """
    global _is_processing, _processing_started_at, _email_agent
    _is_processing = False
    _processing_started_at = None
    _email_agent = None  # Force full re-init on next run
    print("[Email] Processing state manually RESET via /reset endpoint")
    return jsonify({
        'success': True,
        'message': 'Processing state reset. You can now trigger /process again.',
        'timestamp': datetime.utcnow().isoformat()
    })


@app.route('/process', methods=['POST', 'GET'])
def process_emails():
    """
    Trigger email processing. Called by n8n Schedule Trigger → HTTP Request.
    Starts processing in background thread and returns immediately.

    Add ?force=true to force a new run even if processing flag is stuck.
    """
    global _is_processing, _processing_started_at

    force = request.args.get('force', '').lower() == 'true'

    # Auto-reset if stuck too long
    if _is_stuck():
        print(f"[Email] Processing was stuck for >{MAX_PROCESSING_MINUTES}min — auto-resetting")
        _is_processing = False
        _processing_started_at = None

    if _is_processing and not force:
        elapsed = None
        if _processing_started_at:
            elapsed = int((datetime.utcnow() - _processing_started_at).total_seconds())
        return jsonify({
            'success': False,
            'message': 'Processing already in progress',
            'elapsed_seconds': elapsed,
            'tip': 'Add ?force=true to override, or POST to /reset to unstick',
            'last_run': _last_run.isoformat() if _last_run else None
        }), 429

    _is_processing = True
    _processing_started_at = datetime.utcnow()
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
CACHE_TTL = 60

def get_cached_data():
    if time.time() - _data_cache['timestamp'] > CACHE_TTL:
        _data_cache['data'] = get_sheets_service().get_all_data()
        _data_cache['timestamp'] = time.time()
    return _data_cache['data']


@app.route('/api/emails')
def get_emails():
    try:
        data = get_cached_data()
        return jsonify({'success': True, 'data': data, 'count': len(data)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
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
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)