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

