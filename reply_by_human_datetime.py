# reply_by_human_datetime.py
import argparse
import time
from datetime import datetime
import pytz
from gmail_utils import get_gmail_service, list_message_ids, get_message, extract_plain_text_from_message
from summarizers import extractive_summarize
from auto_responder import ensure_label, send_reply_and_label, is_automated_message, is_thread_replied

def to_epoch_ms(date_str, tz_str="Asia/Kolkata", fmt="%Y-%m-%d %H:%M"):
    """
    Convert a local datetime string to epoch milliseconds (UTC).
    Example date_str: "2025-11-28 16:15" (4:15 PM)
    """
    local_tz = pytz.timezone(tz_str)
    naive = datetime.strptime(date_str, fmt)
    local_dt = local_tz.localize(naive)
    utc_dt = local_dt.astimezone(pytz.utc)
    return int(utc_dt.timestamp() * 1000)

def find_by_internal(service, target_ms, tol_ms=300000, query='newer_than:30d', max_results=500):
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
    # convert human datetime to epoch ms (UTC)
    target_ms = to_epoch_ms(args.datetime, tz_str=args.tz, fmt=args.fmt)
    print("Target internalDate (ms, UTC):", target_ms)

    matches = find_by_internal(service, target_ms, tol_ms=int(args.tolerance_min * 60 * 1000),
                               query=args.query, max_results=args.max_results)
    if not matches:
        print("No message found within tolerance. Try increasing --tolerance-min or widening --query.")
        return

    print(f"Found {len(matches)} message(s) within tolerance.")
    label_id = ensure_label(service, label_name=args.label_name)

    for m, internal in matches:
        mid = m.get('id')
        headers = m.get('payload', {}).get('headers', [])
        date_hdr = next((h['value'] for h in headers if h['name'].lower()=='date'), 'N/A')
        subj = next((h['value'] for h in headers if h['name'].lower()=='subject'), 'N/A')
        print("="*60)
        print("Message id:", mid)
        print("internalDate (ms):", internal)
        print("Date header:", date_hdr)
        print("Subject:", subj)

        if is_automated_message(m.get('payload', {})):
            print("Skipping: detected as automated message.")
            continue
        if is_thread_replied(service, m.get('threadId')):
            print("Skipping: thread already has a SENT message.")
            continue

        # extract and summarize
        text = extract_plain_text_from_message(m)
        if args.mode == 'extractive':
            summary = extractive_summarize(text, max_sentences=args.max_sentences)
        else:
            summary = "Transformer mode not enabled in this script."

        print("\n--- Summary ---\n")
        print(summary)
        print("\n--- Reply preview ---\n")
        reply_body = build_reply_from_summary(m, summary, your_name=args.your_name)
        print(reply_body[:1200])

        if args.dry_run:
            print("DRY RUN: not sending. Use --no-dry-run to actually send.")
            continue

        sent = send_reply_and_label(service, m, m['threadId'], reply_body, label_id=label_id, from_email=None)
        print("Sent reply id:", sent.get('id'))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find message by human datetime, summarize and reply.")
    parser.add_argument('--datetime', type=str, required=True,
                        help='Local datetime string, e.g. "2025-11-28 16:15"')
    parser.add_argument('--tz', type=str, default='Asia/Kolkata', help='Timezone of provided datetime (pytz name)')
    parser.add_argument('--fmt', type=str, default='%Y-%m-%d %H:%M', help='Datetime input format (default: %%Y-%%m-%%d %%H:%%M)')
    parser.add_argument('--tolerance-min', type=int, default=5, help='Tolerance window in minutes (default 5)')
    parser.add_argument('--query', type=str, default='after:2025/11/01 before:2025/12/01', help='Gmail query to narrow search range')
    parser.add_argument('--max-results', type=int, default=500)
    parser.add_argument('--mode', type=str, choices=['extractive','transformer'], default='extractive')
    parser.add_argument('--max-sentences', type=int, default=3)
    parser.add_argument('--label-name', type=str, default='AutoReplied')
    parser.add_argument('--your-name', type=str, default='Anvit')
    parser.add_argument('--dry-run', dest='dry_run', action='store_true', default=True)
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false')
    args = parser.parse_args()
    main(args)
