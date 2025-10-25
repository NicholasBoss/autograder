import json
import os
import re
import time
from typing import Literal, Optional

import requests

from utils_text import read_text_from_file


def _load_env(defaults: Optional[dict] = None) -> dict:
    env = dict(defaults or {})
    env.update({k: v for k, v in os.environ.items()})
    return env


def _read_jsonl(path: str) -> list:
    items = []
    if not path or not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def _ensure_dir(p: str) -> None:
    if not p:
        return
    d = p if os.path.isdir(p) else os.path.dirname(p) or "."
    os.makedirs(d, exist_ok=True)


def _first_parsable_attachment(attachments: list) -> Optional[str]:
    if not attachments:
        return None
    for a in attachments:
        path = a.get("saved_path")
        ext = os.path.splitext(path or "")[1].lower()
        if ext in (".txt", ".pdf", ".docx"):
            return path
    return None


def _call_ollama(host: str, model: str, system_prompt: str, user_text: str) -> str:
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    # Ollama returns {message: {content: ...}}
    msg = (data.get("message") or {}).get("content")
    if not msg and isinstance(data.get("choices"), list):
        msg = data["choices"][0]["message"]["content"]
    return msg or ""


def _call_openrouter(api_key: str, model: str, system_prompt: str, user_text: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    }
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if choices:
        return choices[0].get("message", {}).get("content", "")
    return ""


def _read_file_text(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".json", ".txt", ".pdf", ".docx"):
        if ext == ".json":
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    obj = json.load(f)
                if isinstance(obj, dict) and "questions" in obj:
                    # Turn into plain text block
                    parts = []
                    for q in obj.get("questions", []):
                        qid = str(q.get("id")) if isinstance(q.get("id"), (int, str)) else ""
                        ans = q.get("answer") or q.get("expected") or ""
                        if q.get("text"):
                            parts.append(f"Q{qid}: {q['text']}\nAnswer: {ans}")
                        else:
                            parts.append(f"Q{qid}: {ans}")
                    return "\n\n".join(parts)
                return json.dumps(obj, ensure_ascii=False)
            except Exception:
                return ""
        else:
            t = read_text_from_file(path)
            return t or ""
    # unknown extensions: try utf-8
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _parse_numeric_score(text: str) -> Optional[float]:
    if not text:
        return None
    # Patterns like "score: 7/10" or "7 out of 10" or standalone 7.5
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?", text)
    if not m:
        return None
    val = float(m.group(1))
    denom = m.group(2)
    if denom:
        try:
            d = float(denom)
            if d > 0:
                return round(10.0 * val / d, 2) if d != 10 else round(val, 2)
        except Exception:
            pass
    return round(val, 2)


def run_grading(
    backend: Literal["ollama", "openrouter"],
    prompt: str,
    out_path: str,
    canvas_api_url: str,
    canvas_api_token: str,
    course_id: str | int,
    assignment_id: str | int,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_model: str | None = None,
    answer_key_path: str | None = None,
) -> dict:
    start = time.time()

    defaults = {
        "DATA_DIR": "./data",
        "MANIFEST_FILE": "submissions_manifest.jsonl",
    }
    env = _load_env(defaults)
    manifest_path = os.path.join(env.get("DATA_DIR", "./data"), env.get("MANIFEST_FILE", "submissions_manifest.jsonl"))
    submissions = _read_jsonl(manifest_path)
    _ensure_dir(out_path)

    out_f = open(out_path, "a", encoding="utf-8")
    files = 0
    students = 0
    errors = 0

    # Load answer key text (any file type)
    chosen_answer_key_path = answer_key_path
    if not chosen_answer_key_path:
        ak_env = env.get("ANSWER_KEY_FILE")
        if ak_env:
            chosen_answer_key_path = os.path.join(env.get("DATA_DIR", "./data"), ak_env)
    answer_key_text = _read_file_text(chosen_answer_key_path) if chosen_answer_key_path else ""

    # System prompt designed for per-question analysis and JSON output
    system_prompt = (
        "You are an autograder. Compare a student's submission to the provided answer key. "
        "Identify the number of questions and grade each question with a score 0..1 (1=correct, 0=incorrect, partial allowed like 0.5). "
        "Return STRICT JSON with keys: total_questions (int), per_question (list of {qid: string, correct: bool, score: number, feedback: string, expected: string}), "
        "overall_score (number 0..10). Do not include any extra commentary outside JSON."
    )

    for sub in submissions:
        if str(sub.get("course_id")) != str(course_id) or str(sub.get("assignment_id")) != str(assignment_id):
            continue
        students += 1
        text = (sub.get("body_text") or "").strip()
        if not text:
            path = _first_parsable_attachment(sub.get("attachments") or [])
            if path:
                t = read_text_from_file(path)
                if t:
                    text = t
                    files += 1
        if not text:
            out = {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "user_id": sub.get("user_id"),
                "name": sub.get("name"),
                "reply": "",
                "score": None,
                "error": "no_text",
            }
            out_f.write(json.dumps(out, ensure_ascii=False) + "\n")
            continue

        try:
            user_payload = (
                f"ANSWER_KEY:\n{answer_key_text}\n\n"
                f"STUDENT_SUBMISSION:\n{text}\n\n"
                f"GUIDANCE:\n{prompt}"
            )
            if backend == "ollama":
                reply = _call_ollama(ollama_host or "http://localhost:11434", ollama_model or "llama3.1", system_prompt, user_payload)
            else:
                reply = _call_openrouter(openrouter_api_key or "", openrouter_model or "meta-llama/llama-3.1-8b-instruct:free", system_prompt, user_payload)
        except Exception:
            reply = ""
        err = None
        if not reply:
            err = "backend_error"
            errors += 1
        # Try to parse JSON response for structured grading
        per_question = None
        score = None
        if reply:
            try:
                # Extract first JSON object
                import re as _re
                m = _re.search(r"\{[\s\S]*\}", reply)
                js = reply if reply.strip().startswith("{") else (m.group(0) if m else "")
                if js:
                    obj = json.loads(js)
                    pq = obj.get("per_question")
                    if isinstance(pq, list):
                        per_question = pq
                    elif isinstance(pq, dict):
                        # normalize to list
                        per_question = [dict(qid=k, **v) if isinstance(v, dict) else {"qid": k, "score": v} for k, v in pq.items()]
                    oscore = obj.get("overall_score")
                    if isinstance(oscore, (int, float)):
                        score = float(oscore)
            except Exception:
                pass
        if score is None:
            score = _parse_numeric_score(reply)
        rec = {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "user_id": sub.get("user_id"),
            "name": sub.get("name"),
            "reply": reply,
            "score": score,
            "per_question": per_question,
            "error": err,
        }
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    out_f.close()
    elapsed = round(time.time() - start, 2)
    return {
        "students": students,
        "files_read": files,
        "errors": errors,
        "elapsed_secs": elapsed,
        "backend": backend,
        "out_path": out_path,
    }
