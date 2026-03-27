"""Check sheet data for duplicates and missing responses"""
from src.services.sheets_service import GoogleSheetsService

svc = GoogleSheetsService()
data = svc.get_all_data()

print('Sheet Data:')
print('=' * 120)

# Track thread IDs to find duplicates
thread_ids = {}

for row in data:
    sn = row.get('SN', '')
    thread_id = row.get('Thread ID', '')
    subject = row.get('Email Subject', '')[:60]
    sender = row.get('Sender Email', '')
    reply_status = row.get('Reply Status', '')
    replied_by = row.get('Replied By', '')
    
    # Track duplicates
    if thread_id:
        if thread_id in thread_ids:
            thread_ids[thread_id].append(sn)
        else:
            thread_ids[thread_id] = [sn]
    
    print(f'SN {sn}: {subject}')
    print(f'  Thread: {thread_id}')
    print(f'  From: {sender}')
    print(f'  Reply: {reply_status} | By: {replied_by[:60] if replied_by else "(none)"}')
    print()

print('\n' + '=' * 120)
print('DUPLICATE THREADS:')
for thread_id, sns in thread_ids.items():
    if len(sns) > 1:
        print(f'Thread {thread_id} appears in rows: {", ".join(sns)}')
