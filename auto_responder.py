# auto_responder.py
import base64
from email.mime.text import MIMEText
import re
import time

def _headers_to_dict(headers):
    return {h['name'].lower(): h['value'] for h in headers}

def ensure_label(service, label_name="AutoReplied"):
    """Return labelId for label_name; create if missing."""
    labels_resp = service.users().labels().list(userId='me').execute()
    labels = labels_resp.get('labels', [])
    for lab in labels:
        if lab.get('name') == label_name:
            return lab['id']
    # create
    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    lab = service.users().labels().create(userId='me', body=body).execute()
    return lab['id']

def is_thread_replied(service, thread_id):
    """
    Return True if any message in the thread has the 'SENT' label (i.e., user replied or sent a message in thread).
    """
    thread = service.users().threads().get(userId='me', id=thread_id, format='metadata', metadataHeaders=[]).execute()
    for m in thread.get('messages', []):
        labels = m.get('labelIds', [])
        if 'SENT' in labels:
            return True
    return False

def is_automated_message(payload):
    """
    Heuristics to detect automated emails (mailing lists, auto-generated, no-reply).
    payload: message['payload']
    """
    headers = payload.get('headers', [])
    hd = _headers_to_dict(headers)
    subject = hd.get('subject', '').lower()
    from_header = hd.get('from', '').lower()
    # common signals
    if 'list-id' in hd or 'mailer-daemon' in from_header or 'no-reply' in from_header or 'noreply' in from_header:
        return True
    if hd.get('auto-submitted', '').lower() in ('auto-generated','auto-replied','yes'):
        return True
    if re.search(r'^(no-?reply|donotreply|do-?not-?reply)', from_header):
        return True
    # common precedence headers
    if hd.get('precedence', '').lower() in ('bulk', 'list', 'auto_reply'):
        return True
    return False

def get_message_datetime_ms(msg):
    """Return internalDate (ms) as int if present, else 0."""
    try:
        return int(msg.get('internalDate', '0'))
    except Exception:
        return 0

def make_reply_message(to_addr, subject, body_text, in_reply_to=None, references=None, from_email=None):
    msg = MIMEText(body_text, 'plain')
    # Subject should be prefixed with "Re:" if not present
    if not (subject.lower().startswith('re:')):
        subject = "Re: " + subject
    msg['Subject'] = subject
    msg['To'] = to_addr
    if from_email:
        msg['From'] = from_email
    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return raw

def send_reply_and_label(service, orig_msg, thread_id, reply_text, label_id=None, from_email=None):
    """
    orig_msg: Gmail message resource (dict)
    thread_id: thread id string
    reply_text: text body
    label_id: if provided, will be added to the original message after sending
    """
    payload = orig_msg.get('payload', {})
    headers = payload.get('headers', [])
    hd = _headers_to_dict(headers)
    # to -> reply to 'reply-to' if exists else 'from'
    to_addr = hd.get('reply-to', hd.get('from', ''))
    subject = hd.get('subject', '')
    message_id = hd.get('message-id', None)
    references = hd.get('references', None)
    raw = make_reply_message(to_addr, subject, reply_text, in_reply_to=message_id, references=references, from_email=from_email)

    send_body = {'raw': raw, 'threadId': thread_id}
    sent = service.users().messages().send(userId='me', body=send_body).execute()

    # add label to original message to avoid repeated replies
    if label_id:
        try:
            service.users().messages().modify(userId='me', id=orig_msg['id'], body={'addLabelIds': [label_id]}).execute()
        except Exception:
            pass

    return sent

def process_unreplied(service, query='is:unread', reply_template=None, max_results=20,
                       min_age_seconds=60*60*6, label_name='AutoReplied', dry_run=False, from_email=None):
    """
    - query: Gmail search query to select candidate messages (default is unread).
    - reply_template: str or callable(msg)->str. If None, a default template is used.
    - min_age_seconds: only reply to messages older than this (to avoid immediate replies while user may reply)
    - label_name: name for label to mark processed messages.
    - dry_run: True -> only print actions, do not send.
    - from_email: optional From field for outgoing messages.
    """
    if callable(reply_template):
        template_fn = reply_template
    else:
        default_template = ("Hello,\n\nThank you for your message. I have received it and will get back to you shortly.\n\n"
                            "Best regards,\n[Your Name]")
        template_fn = (lambda msg: reply_template) if reply_template else (lambda msg: default_template)

    # ensure label exists
    label_id = ensure_label(service, label_name)

    # list messages
    resp = service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
    msg_ids = [m['id'] for m in resp.get('messages', [])]
    results = []
    now_ms = int(time.time() * 1000)
    for mid in msg_ids:
        msg = service.users().messages().get(userId='me', id=mid, format='full').execute()
        thread_id = msg.get('threadId')
        # skip if already labeled (avoid duplicate processing)
        if label_id in msg.get('labelIds', []):
            results.append({'id': mid, 'skipped': 'already_labeled'})
            continue
        # skip auto messages
        if is_automated_message(msg.get('payload', {})):
            results.append({'id': mid, 'skipped': 'automated'})
            continue
        # only reply if thread has no sent messages by user
        if is_thread_replied(service, thread_id):
            results.append({'id': mid, 'skipped': 'thread_has_reply'})
            continue
        # skip fresh messages within min_age_seconds
        internal_date = get_message_datetime_ms(msg)
        age = (now_ms - internal_date) / 1000.0
        if age < min_age_seconds:
            results.append({'id': mid, 'skipped': 'too_new', 'age_seconds': age})
            continue

        # prepare reply text
        reply_text = template_fn(msg)

        if dry_run:
            results.append({'id': mid, 'action': 'would_send', 'reply_text': reply_text})
            continue

        # send reply
        sent = send_reply_and_label(service, msg, thread_id, reply_text, label_id=label_id, from_email=from_email)
        results.append({'id': mid, 'action': 'sent', 'sent_id': sent.get('id')})

    return results
