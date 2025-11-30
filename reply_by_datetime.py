# reply_by_datetime.py
import argparse
import re
from gmail_utils import get_gmail_service, list_message_ids, get_message, extract_plain_text_from_message
from summarizers import extractive_summarize, transformer_summarize
from auto_responder import ensure_label, send_reply_and_label, is_automated_message, is_thread_replied, get_message_datetime_ms

# Heuristic match on the "Date" header (human readable) and/or internalDate
def message_matches_datetime(headers, target_date_str, target_time_str):
    """
    headers: list of header dicts from message payload
    target_date_str: e.g. "Nov 28"  (case-insensitive substring match)
    target_time_str: e.g. "9:45"    (match hour:minute)
    Returns True on match.
    """
    for h in headers:
        name = h.get('name','').lower()
        val = h.get('value','')
        if name == 'date':
            v = val.lower()
            if target_date_str.lower() in v and target_time_str in v:
                return True
    return False

def find_candidates(service, date_str, time_str, query='after:2025/11/27 before:2025/11/29', max_results=50):
    """Searches messages in the date window and returns list of matching message resources."""
    msg_ids = list_message_ids(service, query=query, max_results=max_results)
    matches = []
    for mid in msg_ids:
        msg = get_message(service, mid)
        headers = msg.get('payload', {}).get('headers', [])
        if message_matches_datetime(headers, date_str, time_str):
            matches.append(msg)
    return matches

def build_reply_from_summary(original_msg, summary_text, your_name="Anvit"):
    headers = original_msg.get('payload', {}).get('headers', [])
    sender = ""
    subj = ""
    for h in headers:
        n = h.get('name','').lower()
        if n == 'from':
            sender = h.get('value','')
        if n == 'subject':
            subj = h.get('value','')
    body_lines = [
        f"Hello,",
        "",
        f"Thank you for your message (re: {subj}). Here is a brief summary of what I understand:",
        "",
        summary_text.strip(),
        "",
        "I will follow up with more details as required.",
        "",
        f"Best regards,",
        your_name
    ]
    return "\n".join(body_lines)

def main(args):
    service = get_gmail_service()
    # narrow the query span to include the date around Nov 28
    # You can edit the query if your mailbox uses different dates
    date_query = args.query
    print("Searching messages with query:", date_query)
    candidates = find_candidates(service, date_str=args.date_substr, time_str=args.time_substr,
                                 query=date_query, max_results=args.max_results)

    if not candidates:
        print("No message found that matches the date/time heuristics. Listing top messages in the date range for inspection...")
        # fallback: list top messages found by the query and show their Date/Subject
        ids = list_message_ids(service, query=date_query, max_results=args.max_results)
        for mid in ids:
            m = get_message(service, mid)
            headers = m.get('payload', {}).get('headers', [])
            date_hdr = next((h['value'] for h in headers if h['name'].lower()=='date'), 'N/A')
            subj = next((h['value'] for h in headers if h['name'].lower()=='subject'), 'N/A')
            print(f"id={mid}  date={date_hdr}  subject={subj}")
        return

    print(f"Found {len(candidates)} candidate(s). We'll inspect them now.")
    label_id = ensure_label(service, label_name=args.label_name)

    for msg in candidates:
        mid = msg.get('id')
        headers = msg.get('payload', {}).get('headers', [])
        date_hdr = next((h['value'] for h in headers if h['name'].lower()=='date'), 'N/A')
        subj = next((h['value'] for h in headers if h['name'].lower()=='subject'), 'N/A')
        print("="*60)
        print(f"Message id: {mid}")
        print(f"Date header: {date_hdr}")
        print(f"Subject: {subj}")

        # safety checks
        if is_automated_message(msg.get('payload', {})):
            print("Skipping: detected as automated message.")
            continue
        if is_thread_replied(service, msg.get('threadId')):
            print("Skipping: thread already has a SENT message.")
            continue

        text = extract_plain_text_from_message(msg)
        # summarize (extractive by default)
        if args.mode == 'extractive':
            summary = extractive_summarize(text, max_sentences=args.max_sentences)
        else:
            summary = transformer_summarize(text, model_name=args.model_name,
                                            max_length=args.max_length, min_length=args.min_length,
                                            chunk_overlap_tokens=args.chunk_overlap_tokens,
                                            device=args.device)
        print("\n--- Generated Summary ---\n")
        print(summary)
        print("\n-------------------------\n")

        reply_body = build_reply_from_summary(msg, summary, your_name=args.your_name)
        print("Reply preview (first 800 chars):\n")
        print(reply_body[:800])
        if args.dry_run:
            print("DRY RUN: not sending. To actually send, run with --no-dry-run.")
            continue

        # send and label
        sent = send_reply_and_label(service, msg, msg['threadId'], reply_body, label_id=label_id, from_email=None)
        print("Sent reply message id:", sent.get('id'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # adjust query range so gmail returns messages around Nov 28
    parser.add_argument('--query', type=str, default='after:2025/11/27 before:2025/11/29', help='Gmail query for date range')
    parser.add_argument('--date-substr', type=str, default='Nov 28', help='Substring to match in Date header (e.g. "Nov 28")')
    parser.add_argument('--time-substr', type=str, default='9:45', help='Substring to match in Date header time (e.g. "9:45")')
    parser.add_argument('--max-results', type=int, default=50)
    parser.add_argument('--mode', type=str, choices=['extractive','transformer'], default='extractive')
    parser.add_argument('--max-sentences', type=int, default=3)
    parser.add_argument('--model-name', type=str, default='sshleifer/distilbart-cnn-12-6')
    parser.add_argument('--max-length', type=int, default=130)
    parser.add_argument('--min-length', type=int, default=30)
    parser.add_argument('--chunk-overlap-tokens', type=int, default=128)
    parser.add_argument('--device', type=int, default=-1)
    parser.add_argument('--dry-run', dest='dry_run', action='store_true', default=True, help='Do not actually send replies')
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false', help='Actually send replies')
    parser.add_argument('--label-name', type=str, default='AutoReplied')
    parser.add_argument('--your-name', type=str, default='Anvit')
    args = parser.parse_args()
    main(args)
