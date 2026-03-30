"""
Flask Web Application - Email Dashboard
Displays email tracking data from Google Sheets in a beautiful table interface.
Includes /process endpoint for n8n or external cron triggers.
"""
from flask import Flask, jsonify, request
from src.services.sheets_service import GoogleSheetsService
from config import Config
import os
import threading
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Initialize Google Sheets Service
sheets_service = GoogleSheetsService()

# Track processing state to prevent overlapping runs
_processing_lock = threading.Lock()
_is_processing = False
_last_run = None
_last_result = None


def _run_email_processing():
    """Background thread that does the actual email processing."""
    global _is_processing, _last_run, _last_result
    try:
        from main import EmailToSheetsAgent
        agent = EmailToSheetsAgent()
        count = agent.process_emails()
        _last_run = datetime.utcnow()
        _last_result = {'processed': count, 'status': 'success'}
        print(f"[Process] Completed. Processed {count} emails at {_last_run.isoformat()}")
    except Exception as e:
        _last_run = datetime.utcnow()
        _last_result = {'error': str(e), 'status': 'failed'}
        print(f"[Process] Failed: {e}")
    finally:
        _is_processing = False
        _processing_lock.release()


@app.route('/')
def index():
    """Status page."""
    return jsonify({
        'service': 'Email-to-Sheets Agent',
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
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'processing': _is_processing,
        'timestamp': datetime.utcnow().isoformat(),
        'last_run': _last_run.isoformat() if _last_run else None,
        'last_result': _last_result
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


@app.route('/api/emails')
def get_emails():
    """API endpoint to fetch all emails data."""
    try:
        data = sheets_service.get_all_data()
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
        data = sheets_service.get_all_data()
        
        # Calculate statistics
        total_emails = len(data)
        replied_emails = len([d for d in data if d.get('Reply Status') == 'Replied'])
        pending_emails = total_emails - replied_emails
        
        # Unique senders
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




