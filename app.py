"""
Flask Web Application - Email Dashboard
Displays email tracking data from Google Sheets in a beautiful table interface.
"""
from flask import Flask, render_template, jsonify
from src.services.sheets_service import GoogleSheetsService
from config import Config
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Initialize Google Sheets Service
sheets_service = GoogleSheetsService()


@app.route('/')
def index():
    """Main dashboard page with email table."""
    return render_template('index.html')


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
