# reply_by_internal.py
import argparse
from gmail_utils import get_gmail_service, list_message_ids, get_message, extract_plain_text_from_message
from summarizers import extractive_summarize
from auto_responder import ensure_label, send_reply_and_label, is_automated_message, is_thread_replied

def find_by_internal(service, target_ms, tol_ms=300000, query='after:2025/11/27 before:2025/11/29', max_results=200):
    ids = list_message_ids(service, query=query, max_results=max_results)
    matches = []
    for mid in ids:
        m = get_message(service, mid)
        internal = int(m.get('internalDate', '0'))
        if abs(internal - target_ms) <= tol_ms:
            matches.append((m, internal))
    return matches

def build_reply_from_summary(original_msg, summary_text, your_name="Anvit"):
    headers = original_msg.get('payload', {}).get('headers', [])
    subj = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(no subject)')
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
    print("Searching messages with query:", args.query)
    matches = find_by_internal(service, args.target_ms, tol_ms=args.tolerance_ms, query=args.query, max_results=args.max_results)
    if not matches:
        print("No matches found by internalDate within tolerance.")
        return
    print(f"Found {len(matches)} candidate(s).")
    label_id = ensure_label(service, label_name=args.label_name)
    for m, internal in matches:
        mid = m.get('id')
        print("="*60)
        print("Message id:", mid)
        print("internalDate (ms):", internal)
        headers = m.get('payload', {}).get('headers', [])
        date_hdr = next((h['value'] for h in headers if h['name'].lower()=='date'), 'N/A')
        subj = next((h['value'] for h in headers if h['name'].lower()=='subject'), 'N/A')
        print("Date header:", date_hdr)
        print("Subject:", subj)

        if is_automated_message(m.get('payload', {})):
            print("Skipping: automated message")
            continue
        if is_thread_replied(service, m.get('threadId')):
            print("Skipping: thread already has a SENT message")
            continue

        text = extract_plain_text_from_message(m)
        summary = extractive_summarize(text, max_sentences=args.max_sentences)
        print("\n--- Summary ---\n")
        print(summary)
        print("\n--- Reply preview (first 800 chars) ---\n")
        reply_body = build_reply_from_summary(m, summary, your_name=args.your_name)
        print(reply_body[:800])
        if args.dry_run:
            print("DRY RUN: not sending.")
            continue
        sent = send_reply_and_label(service, m, m['threadId'], reply_body, label_id=label_id, from_email=None)
        print("Sent reply id:", sent.get('id'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-ms', type=int, required=True, help='Target internalDate in milliseconds (UTC epoch ms)')
    parser.add_argument('--tolerance-ms', type=int, default=300000, help='Tolerance window in ms (default 5 minutes)')
    parser.add_argument('--query', type=str, default='after:2025/11/27 before:2025/11/29')
    parser.add_argument('--max-results', type=int, default=200)
    parser.add_argument('--max-sentences', type=int, default=3)
    parser.add_argument('--label-name', type=str, default='AutoReplied')
    parser.add_argument('--your-name', type=str, default='Anvit')
    parser.add_argument('--dry-run', dest='dry_run', action='store_true', default=True)
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false')
    args = parser.parse_args()
    main(args)
