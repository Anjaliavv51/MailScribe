# gmail_utils.py
import base64
import os
import re
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send'
]


def get_gmail_service(credentials_path='credentials.json', token_path='token.json'):
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
    service = build('gmail', 'v1', credentials=creds)
    return service

def list_message_ids(service, query=None, max_results=10):
    """Return list of message ids matching query (None means all)."""
    results = service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
    return [m['id'] for m in results.get('messages', [])]

def get_message(service, msg_id):
    """Fetch message payload (full format)."""
    return service.users().messages().get(userId='me', id=msg_id, format='full').execute()

def extract_plain_text_from_message(msg):
    """
    Extract best-effort plain text from a Gmail message payload.
    Handles multipart, text/plain, and text/html fallback.
    """
    payload = msg.get('payload', {})
    parts = payload.get('parts')
    if not parts:
        # single-part message (body in payload['body']['data'])
        body = payload.get('body', {}).get('data', '')
        return _safe_base64_decode(body)
    # Walk parts to find 'text/plain' first, else 'text/html'
    text_parts = []
    html_parts = []
    def walk(parts_list):
        for p in parts_list:
            mime = p.get('mimeType', '')
            if mime == 'text/plain':
                text_parts.append(p)
            elif mime == 'text/html':
                html_parts.append(p)
            elif p.get('parts'):
                walk(p.get('parts'))
    walk(parts)
    if text_parts:
        return "\n\n".join(_safe_base64_decode(p.get('body', {}).get('data', '')) for p in text_parts)
    if html_parts:
        combined = "\n\n".join(_safe_base64_decode(p.get('body', {}).get('data', '')) for p in html_parts)
        return html_to_text(combined)
    # fallback: try direct body
    body = payload.get('body', {}).get('data', '')
    return html_to_text(_safe_base64_decode(body))

def _safe_base64_decode(data):
    if not data:
        return ''
    data = data.replace('-', '+').replace('_', '/')
    padding = len(data) % 4
    if padding:
        data += "=" * (4 - padding)
    try:
        decoded = base64.b64decode(data).decode('utf-8', errors='replace')
        return decoded
    except Exception:
        return ''

def html_to_text(html):
    if not html:
        return ''
    soup = BeautifulSoup(html, 'html.parser')
    # remove scripts/styles
    for s in soup(['script', 'style']):
        s.decompose()
    text = soup.get_text(separator='\n')
    # collapse whitespace
    lines = [line.strip() for line in text.splitlines()]
    cleaned = '\n'.join([ln for ln in lines if ln])
    return cleaned
