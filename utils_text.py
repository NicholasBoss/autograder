<<<<<<< HEAD
# utils_text.py
import re
import os
import io
from typing import Optional, Dict, List
from pdfminer.high_level import extract_text as pdf_extract_text
from docx import Document

_filename_sanitize_pattern = re.compile(r'[^A-Za-z0-9_.\-\s]')

def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = _filename_sanitize_pattern.sub('', name)
    name = re.sub(r'\s+', '_', name)
    return name[:255]

def read_text_from_file(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    lower = path.lower()
    try:
        if lower.endswith('.txt'):
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif lower.endswith('.pdf'):
            return extract_text_from_pdf_file(path)
        elif lower.endswith('.docx'):
            return extract_text_from_docx_file(path)
        else:
            # try by extension fallback: try reading as text
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
    except Exception:
        return None

def extract_text_from_pdf_file(path: str) -> str:
    try:
        return pdf_extract_text(path) or ""
    except Exception:
        # fallback to empty string on errors
        return ""

def extract_text_from_docx_file(path: str) -> str:
    try:
        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs)
    except Exception:
        return ""

def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    try:
        # pdfminer can read from a file-like object
        with io.BytesIO(pdf_bytes) as stream:
            return pdf_extract_text(stream) or ""
    except Exception:
        return ""

def extract_text_from_docx_bytes(docx_bytes: bytes) -> str:
    try:
        with io.BytesIO(docx_bytes) as stream:
            doc = Document(stream)
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""

def slice_answers_into_questions(text: str, answer_key: Dict) -> Dict[str, str]:
    """
    Very simple slicing: looks for question markers in the answer_key and splits by them.
    answer_key is expected to be dict qid -> {'prompt': '...', 'keywords': [...], 'max_score': 1}
    If no markers found, return entire text under qid 'q1'.
    """
    out = {}
    if not text:
        return {qid: "" for qid in answer_key.keys()}
    lowered = text
    # try to split by lines that start with Q1, Q2, etc, or "Question 1"
    lines = text.splitlines()
    current_q = None
    buffer: List[str] = []
    for line in lines:
        m = re.match(r'^\s*(?:q|question)[\s\._\-]*([0-9]+)\b', line.strip(), re.I)
        if m:
            if current_q and buffer:
                out[current_q] = "\n".join(buffer).strip()
            current_q = f"q{m.group(1)}"
            buffer = []
        else:
            buffer.append(line)
    if current_q:
        out[current_q] = "\n".join(buffer).strip()
    # If we didn't detect question markers, try to map by answer_key keys in sequence
    if not out:
        # naive split by blank-line into chunks, map to keys
        chunks = [c.strip() for c in re.split(r'\n\s*\n', text) if c.strip()]
        keys = list(answer_key.keys())
        for i, k in enumerate(keys):
            out[k] = chunks[i] if i < len(chunks) else ""
    # ensure all keys exist
    for k in answer_key.keys():
        out.setdefault(k, "")
    return out

def heuristic_score(text: str, rubric: str, keywords: List[str], max_score: int) -> float:
    """
    Simple heuristic:
      - base 0
      - +50% of max if rubric keywords present (proportional)
      - + extra for length (scaled)
      - clamp to max_score
    """
    if not text or not text.strip():
        return 0.0
    score = 0.0
    text_lower = text.lower()
    # keyword hits
    if keywords:
        hits = sum(1 for kw in keywords if kw.lower() in text_lower)
        score += (hits / max(1, len(keywords))) * (max_score * 0.6)
    # rubric presence (simple)
    rubric_lower = (rubric or "").lower()
    if rubric_lower:
        # reward if rubric's important phrases appear
        rubric_tokens = [t for t in re.split(r'\W+', rubric_lower) if t]
        matches = sum(1 for t in set(rubric_tokens) if t in text_lower)
        score += min(max_score * 0.3, (matches / max(1, len(rubric_tokens))) * (max_score * 0.3))
    # length factor: short answers get penalized
    length = len(text.split())
    length_score = min(max_score * 0.1, (min(length, 300) / 300) * (max_score * 0.1))
    score += length_score
    # clamp
    return min(float(max_score), round(score, 2))
=======
import io
import os
import re
import unicodedata
from typing import Optional

from pdfminer.high_level import extract_text as pdf_extract_text
from docx import Document


SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_. ")


def sanitize_filename(name: str) -> str:
    if not name:
        return "untitled"
    # Normalize and strip unsafe characters
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(ch if ch in SAFE_CHARS else "_" for ch in name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ ")
    return cleaned or "file"


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    try:
        with io.BytesIO(pdf_bytes) as f:
            return pdf_extract_text(f) or ""
    except Exception:
        return ""


def extract_text_from_docx(docx_bytes: bytes) -> str:
    try:
        with io.BytesIO(docx_bytes) as f:
            doc = Document(f)
            return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception:
        return ""


def read_text_from_file(path: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        if ext == ".pdf":
            with open(path, "rb") as f:
                return extract_text_from_pdf(f.read())
        if ext == ".docx":
            with open(path, "rb") as f:
                return extract_text_from_docx(f.read())
    except Exception:
        return None
    return None


_QNUM = re.compile(r"(^|\n)\s*(?:Q|Question|)(\d{1,2})[\).:-]?\s", re.IGNORECASE)


def slice_answers_into_questions(text: str, answer_key: dict) -> dict[str, str]:
    if not text:
        return {}
    questions = []
    if isinstance(answer_key, dict) and "questions" in answer_key:
        for q in answer_key.get("questions", []):
            qid = str(q.get("id") or q.get("qid") or q.get("number") or q.get("name") or "")
            if not qid:
                continue
            questions.append(qid)
    # Try numeric split (Q1/Q2...)
    parts = []
    last = 0
    matches = list(_QNUM.finditer(text))
    if matches:
        for i, m in enumerate(matches):
            if i > 0:
                parts.append(text[last:m.start()])
            last = m.end()
        parts.append(text[last:])
    else:
        # Fallback: single chunk
        parts = [text]

    out: dict[str, str] = {}
    if questions and len(parts) >= len(questions):
        for i, qid in enumerate(questions):
            out[str(qid)] = parts[i].strip()
    else:
        # Map by detected numbers
        if matches:
            for i, m in enumerate(matches):
                num = m.group(2)
                out[num] = parts[i].strip() if i < len(parts) else ""
        else:
            out["1"] = text.strip()
    return out


def heuristic_score(text: str, rubric: str, keywords: list[str], max_score: int) -> float:
    if not text:
        return 0.0
    text_l = text.lower()
    total = len(keywords) or 1
    hits = 0
    for kw in keywords:
        kw = (kw or "").lower().strip()
        if not kw:
            continue
        # Simple containment; partial credit with stemming-ish handling
        if kw in text_l:
            hits += 1
        else:
            # token overlap heuristic
            tk = set(re.findall(r"\w+", kw))
            if tk and len(tk & set(re.findall(r"\w+", text_l))) >= max(1, int(0.6 * len(tk))):
                hits += 0.5
    score = (hits / total) * (max_score or 0)
    return float(round(score, 2))

>>>>>>> origin/Chase
