"""Quick test to verify HTML stripping works on real emails."""
from src.services.gmail_service import GmailService

gmail = GmailService()
emails = gmail.fetch_recent_emails()
print(f"Total emails: {len(emails)}")

# Find emails that might have had HTML issues
found = 0
for e in emails:
    body = e.get("body", "")
    subj = e.get("subject", "?")
    # Look for ticket notifications or any remaining HTML
    if "<div" in body or "<html" in body or "<table" in body:
        print(f"\n!!! STILL HAS HTML TAGS !!!")
        print(f"Subject: {subj[:80]}")
        print(f"Thread: {e.get('thread_id', '?')}")
        print(f"Body: {body[:500]}")
        print("---")
        found += 1
        if found >= 3:
            break
    elif "ticket" in body.lower() or "comment" in body.lower():
        print(f"\nTicket email (clean text):")
        print(f"Subject: {subj[:80]}")
        print(f"Body: {body[:400]}")
        print("---")
        found += 1
        if found >= 3:
            break

if found == 0:
    print("\nAll emails have clean plain text bodies - HTML stripping works!")
