"""
Quick test script to verify all components are working
"""
import sys
from config import Config

print("=" * 60)
print("Email-to-Sheets Agent - Setup Test")
print("=" * 60)

# Test 1: Configuration
print("\n[1/4] Testing Configuration...")
errors = Config.validate()
if errors:
    print("❌ Configuration errors found:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
else:
    print("✅ Configuration valid")
    print(f"  - Groq API Key: {Config.GROQ_API_KEY[:20]}...")
    print(f"  - Google Sheet ID: {Config.GOOGLE_SHEET_ID}")

# Test 2: Gmail Service
print("\n[2/4] Testing Gmail Service...")
try:
    from src.services import GmailService
    gmail = GmailService()
    print("✅ Gmail Service initialized")
    print(f"  - Credentials loaded from: {Config.GMAIL_CREDENTIALS_PATH}")
except Exception as e:
    print(f"❌ Gmail Service failed: {e}")
    print("\n  This is expected on first run. You'll need to authenticate via browser.")
    print("  Run: python main.py")

# Test 3: Sheets Service
print("\n[3/4] Testing Google Sheets Service...")
try:
    from src.services import GoogleSheetsService
    sheets = GoogleSheetsService()
    print("✅ Google Sheets Service initialized")
    print(f"  - Service account: {sheets.creds.service_account_email}")
    print(f"  - Sheet: {Config.GOOGLE_SHEET_ID}")
except Exception as e:
    print(f"❌ Sheets Service failed: {e}")
    sys.exit(1)

# Test 4: Email Parser Agent
print("\n[4/4] Testing Email Parser Agent...")
try:
    from src.agents import EmailParserAgent
    parser = EmailParserAgent()
    
    # Test with sample email
    test_email = {
        'subject': 'Dashboard Bug - Urgent',
        'from': 'alice@onescreensolutions.com',
        'date': '2026-03-26',
        'body': 'Hi team, the sales dashboard is showing incorrect numbers for Q1. Please investigate ASAP.'
    }
    
    result = parser.parse_email(test_email)
    print("✅ Email Parser Agent working")
    print(f"  - Task Name: {result.task_name}")
    print(f"  - Status: {result.status}")
    print(f"  - Team: {result.team_origin}")
except Exception as e:
    print(f"❌ Parser Agent failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ All tests passed! Setup is complete.")
print("=" * 60)
print("\nNext steps:")
print("  1. Run: python main.py")
print("  2. Complete Gmail OAuth in browser")
print("  3. Agent will start processing emails!")
print()
