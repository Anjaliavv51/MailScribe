# summarizers.py
from collections import defaultdict
import re

# ---------- Extractive summarizer (lightweight, no heavy deps) ----------
def extractive_summarize(text, max_sentences=3):
    """
    Frequency-based extractive summarizer:
    - splits sentences with a simple regex
    - scores by word frequency (ignores a small stoplist)
    - returns top-ranked sentences in original order
    """
    if not text:
        return ""

    # naive sentence split
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    # lowercase words
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    stopwords = set([
        'the','is','and','to','that','a','of','for','in','on','if','as','all','any','your','you','this','are',
        'we','our','will','be','by','with','from','at','it','has','have','an'
    ])
    freq = defaultdict(int)
    for w in words:
        if w not in stopwords:
            freq[w] += 1
    # score sentences
    scores = []
    for i, s in enumerate(sentences):
        wds = re.findall(r'\b[a-zA-Z]+\b', s.lower())
        score = sum(freq.get(w, 0) for w in wds)
        scores.append((i, s, score))
    # top sentences by score
    top = sorted(scores, key=lambda x: x[2], reverse=True)[:max_sentences]
    # sort back to original order
    top_sorted = sorted(top, key=lambda x: x[0])
    return " ".join(t[1] for t in top_sorted)

# ---------- Transformer-based abstractive summarizer ----------
# put this in summarizers.py replacing the previous transformer_summarize
def transformer_summarize(text, model_name='sshleifer/distilbart-cnn-12-6',
                          max_length=130, min_length=30, chunk_overlap_tokens=128, device=-1):
    """
    Token-aware chunking for transformer summarization.
    - Splits by tokenizer tokens (not characters).
    - Summarizes each chunk and then (optionally) summarizes the concatenated chunk summaries.
    - device: -1 -> CPU, otherwise cuda device id (0,1,...)
    """
    if not text:
        return ""

    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM, pipeline
        import math
    except Exception as e:
        raise RuntimeError("transformers not installed or failed to import. Install transformers and torch to use this function.") from e

    # load tokenizer & model
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    # set device for pipeline
    device_id = -1 if device == -1 else int(device)
    summarizer = pipeline('summarization', model=model, tokenizer=tokenizer, device=device_id)

    # model max length for encoder (tokenizer/model config)
    # many encoder-decoder models use `model.config.max_position_embeddings` or `tokenizer.model_max_length`
    token_limit = getattr(tokenizer, "model_max_length", None)
    if token_limit is None:
        token_limit = 1024
    # keep some headroom for special tokens
    token_limit = int(token_limit)

    # tokenise whole text into ids (fast)
    all_ids = tokenizer.encode(text, add_special_tokens=False)

    # if it fits, do single-pass
    if len(all_ids) <= token_limit:
        out = summarizer(text, max_length=max_length, min_length=min_length, do_sample=False)
        return out[0]['summary_text']

    # otherwise chunk by token ids with overlap
    chunks = []
    start = 0
    chunk_size = token_limit - 16  # small safety margin
    overlap = min(chunk_overlap_tokens, chunk_size//2)
    while start < len(all_ids):
        end = min(start + chunk_size, len(all_ids))
        chunk_ids = all_ids[start:end]
        chunk_text = tokenizer.decode(chunk_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        chunks.append(chunk_text)
        if end == len(all_ids):
            break
        start = end - overlap

    # summarize each chunk
    chunk_summaries = []
    for c in chunks:
        try:
            s = summarizer(c, max_length=max_length, min_length=min_length, do_sample=False)
            chunk_summaries.append(s[0]['summary_text'])
        except Exception:
            # fallback: shorter generation parameters if a chunk still fails
            s = summarizer(c, max_length=max(60, max_length//2), min_length=10, do_sample=False)
            chunk_summaries.append(s[0]['summary_text'])

    # if only one chunk summary, return it
    if len(chunk_summaries) == 1:
        return chunk_summaries[0]

    # combine chunk summaries and do a final (short) summarization pass
    combined = " ".join(chunk_summaries)
    # if combined is still big, limit by tokenizing & trimming
    combined_ids = tokenizer.encode(combined, add_special_tokens=False)
    if len(combined_ids) > token_limit:
        combined_ids = combined_ids[:token_limit - 2]
        combined = tokenizer.decode(combined_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True)

    final = summarizer(combined, max_length=max_length, min_length=min_length, do_sample=False)
    return final[0]['summary_text']
