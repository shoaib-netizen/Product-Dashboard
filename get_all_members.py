# save as get_all_members.py
from dotenv import load_dotenv
load_dotenv()

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import Config
from collections import defaultdict

creds = Credentials.from_authorized_user_file(Config.CHAT_TOKEN_PATH, Config.CHAT_SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
    with open(Config.CHAT_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

service = build("chat", "v1", credentials=creds, cache_discovery=False)

# ── Fetch all messages since Jan 1 ──────────────────────────────────────────
print("Fetching messages... please wait\n")
all_messages = []
next_page = None

while True:
    resp = service.spaces().messages().list(
        parent=f"spaces/{Config.CHAT_SPACE_ID}",
        pageSize=100,
        pageToken=next_page,
        filter='createTime > "2026-01-01T00:00:00Z"',
        orderBy="createTime ASC",
        showDeleted=False,
    ).execute()
    all_messages.extend(resp.get("messages", []))
    next_page = resp.get("nextPageToken")
    if not next_page:
        break

# ── Group messages by sender ID ──────────────────────────────────────────────
by_user = defaultdict(list)
for msg in all_messages:
    uid = msg.get("sender", {}).get("name", "unknown")
    text = (msg.get("text", "") or msg.get("fallbackText", "")).strip()
    if text:
        by_user[uid].append(text)

# ── Print results ────────────────────────────────────────────────────────────
print("=" * 65)
print(f"  TOTAL UNIQUE SENDERS FOUND: {len(by_user)}")
print(f"  TOTAL MESSAGES FETCHED    : {len(all_messages)}")
print("=" * 65)

for i, (uid, msgs) in enumerate(by_user.items(), 1):
    print(f"\n[{i}] USER ID : {uid}")
    print(f"    MESSAGES: {len(msgs)} total")
    print(f"    SAMPLES :")
    for m in msgs[:4]:
        print(f"      → {m[:100]}")

print("\n" + "=" * 65)
print("  Match each USER ID above to a person by reading their messages.")
print("  Then update ALLOWED_USER_IDS in chat_service.py accordingly.")
print("=" * 65)