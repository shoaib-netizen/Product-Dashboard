import json
from google_auth_oauthlib.flow import InstalledAppFlow
from config import Config

def generate_token():
    print("Starting Gmail OAuth flow...")
    
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json',
        Config.GMAIL_SCOPES
    )
    
    # This opens browser and gives you the auth link
    creds = flow.run_local_server(port=0)
    
    # Save token.json
    with open('token.json', 'w') as f:
        f.write(creds.to_json())
    
    print("\n✅ token.json generated successfully!")
    print("\n--- Copy this into your .env as GMAIL_TOKEN_JSON ---")
    print(creds.to_json())
    print("----------------------------------------------------")

if __name__ == "__main__":
    generate_token()