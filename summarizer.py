# summarizer.py
import argparse
from gmail_utils import get_gmail_service, list_message_ids, get_message, extract_plain_text_from_message
from summarizers import extractive_summarize, transformer_summarize
from auto_responder import (
    ensure_label, is_thread_replied, is_automated_message,
    get_message_datetime_ms, send_reply_and_label
)

def build_reply_from_summary(original_msg, summary_text, your_name="Anvit"):
    """
    Build a polite reply using the summary. You can customize this template.
    """
    # Try to extract sender name from headers for personalization (best-effort)
    headers = original_msg.get('payload', {}).get('headers', [])
    sender = None
    for h in headers:
        if h.get('name', '').lower() == 'from':
            sender = h.get('value')
            break
    # Compose reply body
    body_lines = [
        "Hello,",
        "",
        "Thank you for your message. Here is a brief summary of what I understand:",
        "",
        summary_text.strip(),
        "",
        "I will follow up with more details as required.",
        "",
        f"Best regards,",
        your_name
    ]
    return "\n".join(body_lines)

def should_auto_reply(msg, service, min_age_seconds):
    """
    Run safety checks before auto-replying:
    - Skip if automated mailing (no-reply, list, auto-submitted etc.)
    - Skip if thread has any SENT messages (user already replied)
    - Skip if message too new (min_age_seconds)
    - Skip if already labeled AutoReplied (handled in send_reply_and_label logic)
    """
    # Automated / mailing-list detection
    if is_automated_message(msg.get('payload', {})):
        return False, "automated"

    # Thread replied?
    thread_id = msg.get('threadId')
    if is_thread_replied(service, thread_id):
        return False, "thread_has_reply"

    # Age check
    now_ms = __import__("time").time() * 1000
    internal_date = get_message_datetime_ms(msg)
    age_seconds = (now_ms - internal_date) / 1000.0 if internal_date else None
    if age_seconds is not None and age_seconds < min_age_seconds:
        return False, f"too_new ({age_seconds:.0f}s)"

    return True, "ok"

def main(args):
    service = get_gmail_service()

    # Ensure AutoReplied label exists (for marking after sending)
    label_id = ensure_label(service, label_name=args.label_name)

    # fetch message ids matching query
    msg_ids = list_message_ids(service, query=args.query, max_results=args.max_results)
    if not msg_ids:
        print("No messages found.")
        return

    # iterate messages
    for mid in msg_ids:
        msg = get_message(service, mid)
        text = extract_plain_text_from_message(msg)
        print("="*80)
        print(f"Message id: {mid}")
        print("Original (first 800 chars):\n")
        print(text[:800])
        print("\n--- Summary ---\n")

        # create summary
        if args.mode == 'extractive':
            summary = extractive_summarize(text, max_sentences=args.max_sentences)
        else:
            summary = transformer_summarize(
                text,
                model_name=args.model_name,
                max_length=args.max_length,
                min_length=args.min_length,
                chunk_overlap_tokens=args.chunk_overlap_tokens,
                device=args.device
            )
        print(summary)
        print("\n")

        # If auto-reply not enabled, continue
        if not args.auto_reply:
            continue

        # Safety checks
        ok, reason = should_auto_reply(msg, service, args.min_age_seconds)
        if not ok:
            print(f"Skipping auto-reply: {reason}")
            continue

        # Build reply text: if user provided a custom template string, use it with {summary}
        if args.reply_template:
            if "{summary}" in args.reply_template:
                reply_text = args.reply_template.format(summary=summary)
            else:
                # if template has no placeholder, append summary
                reply_text = args.reply_template + "\n\n" + summary
        else:
            # default template that includes the generated summary
            reply_text = build_reply_from_summary(msg, summary, your_name=args.your_name)

        # Dry-run: show what we'd send
        if args.dry_run:
            print("DRY RUN - would send reply (not actually sent).")
            print("Reply body preview:\n")
            print(reply_text[:1000])
            continue

        # Send reply and add label (sends in the thread)
        try:
            sent = send_reply_and_label(service, msg, msg['threadId'], reply_text, label_id=label_id, from_email=None)
            print(f"Sent auto-reply message id: {sent.get('id')}")
        except Exception as e:
            print("Failed to send auto-reply:", e)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gmail summarizer + optional auto-responder")
    parser.add_argument('--query', type=str, default='is:unread', help='Gmail search query (e.g. "is:unread")')
    parser.add_argument('--max-results', type=int, default=5)
    parser.add_argument('--mode', type=str, choices=['extractive','transformer'], default='extractive')
    parser.add_argument('--max-sentences', type=int, default=3)
    parser.add_argument('--model-name', type=str, default='sshleifer/distilbart-cnn-12-6')
    parser.add_argument('--max-length', type=int, default=130)
    parser.add_argument('--min-length', type=int, default=30)
    # transformer chunking args (only relevant for transformer mode)
    parser.add_argument('--chunk-overlap-tokens', type=int, default=128)
    parser.add_argument('--device', type=int, default=-1, help='-1 for CPU, 0 for cuda:0 etc.')
    # auto-reply flags
    parser.add_argument('--auto-reply', action='store_true', help='Enable sending auto-replies after summarizing')
    parser.add_argument('--dry-run', action='store_true', default=True, help='If set, do not actually send replies (default True). Use --no-dry-run to send')
    parser.add_argument('--no-dry-run', dest='dry_run', action='store_false', help='Disable dry-run and actually send replies')
    parser.add_argument('--min-age-seconds', type=int, default=60*60*6, help='Only auto-reply to messages older than this (seconds)')
    parser.add_argument('--reply-template', type=str, default=None, help='Optional reply template. Use {summary} placeholder to include generated summary')
    parser.add_argument('--label-name', type=str, default='AutoReplied', help='Label name to add to messages after replying')
    parser.add_argument('--your-name', type=str, default='Anvit', help='Name to sign replies with')
    args = parser.parse_args()
    main(args)
