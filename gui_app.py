# gui_app.py
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading

def run_in_thread(fn):
    def wrapper(*a, **kw):
        t = threading.Thread(target=fn, args=a, kwargs=kw, daemon=True)
        t.start()
    return wrapper

class App:
    def __init__(self, root):
        self.root = root
        root.title("NLP Email Summarizer & Auto-Responder")
        root.geometry("900x650")
        frm = tk.Frame(root)
        frm.pack(fill="x", padx=10, pady=6)
        self.fetch_btn = tk.Button(frm, text="Fetch & Summarize Unread", command=self.fetch_summarize)
        self.fetch_btn.pack(side="left", padx=5)
        self.reply_btn = tk.Button(frm, text="Auto-Reply (Dry Run)", command=self.auto_reply_dry)
        self.reply_btn.pack(side="left", padx=5)
        self.send_btn = tk.Button(frm, text="Auto-Reply (Send)", command=self.auto_reply_send)
        self.send_btn.pack(side="left", padx=5)
        self.out = scrolledtext.ScrolledText(root, wrap=tk.WORD)
        self.out.pack(fill="both", expand=True, padx=10, pady=6)
        self.status = tk.Label(root, text="Ready", anchor="w")
        self.status.pack(fill="x")

    @run_in_thread
    def fetch_summarize(self):
        try:
            self.status.config(text="Fetching messages...")
            from gmail_utils import get_gmail_service, list_message_ids, get_message, extract_plain_text_from_message
            from summarizers import extractive_summarize
            service = get_gmail_service()
            ids = list_message_ids(service, query='is:unread', max_results=5)
            if not ids:
                self.out.insert(tk.END, "No unread messages found.\n")
            for mid in ids:
                msg = get_message(service, mid)
                text = extract_plain_text_from_message(msg)
                summary = extractive_summarize(text, max_sentences=3)
                self.out.insert(tk.END, "="*60 + "\n")
                self.out.insert(tk.END, f"Message ID: {mid}\n")
                self.out.insert(tk.END, f"Summary:\n{summary}\n\n")
            self.status.config(text="Done fetching.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status.config(text="Error")

    @run_in_thread
    def auto_reply_dry(self):
        try:
            self.status.config(text="Running auto-responder (dry-run)...")
            from auto_responder import process_unreplied
            from gmail_utils import get_gmail_service
            service = get_gmail_service()
            res = process_unreplied(service, query='is:unread', reply_template=None, max_results=5, dry_run=True)
            self.out.insert(tk.END, "Auto-responder dry-run results:\n")
            self.out.insert(tk.END, str(res) + "\n")
            self.status.config(text="Auto-responder dry-run complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status.config(text="Error")

    @run_in_thread
    def auto_reply_send(self):
        try:
            if not messagebox.askyesno("Confirm", "Are you sure you want to SEND auto-replies?"):
                return
            self.status.config(text="Running auto-responder (sending)...")
            from auto_responder import process_unreplied
            from gmail_utils import get_gmail_service
            service = get_gmail_service()
            res = process_unreplied(service, query='is:unread', reply_template=None, max_results=5, dry_run=False)
            self.out.insert(tk.END, "Auto-responder sent results:\n")
            self.out.insert(tk.END, str(res) + "\n")
            self.status.config(text="Auto-responder send complete.")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.status.config(text="Error")

if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.mainloop()
