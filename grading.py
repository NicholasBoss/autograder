# grading.py
import os
import json
import time
from typing import Literal, Optional, Dict
import requests
from utils_text import read_text_from_file, extract_text_from_pdf_bytes, extract_text_from_docx_bytes

def _call_ollama(host: str, model: str, system_prompt: str, user_text: str, timeout=60) -> Dict:
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ]
    }
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _call_openrouter(api_key: str, model: str, system_prompt: str, user_text: str, timeout=60) -> Dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "max_tokens": 1024
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def run_grading(
    backend: Literal["ollama", "openrouter"],
    prompt: str,
    out_path: str,
    canvas_api_url: str,
    canvas_api_token: str,
    course_id,
    assignment_id,
    ollama_host: Optional[str] = None,
    ollama_model: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    openrouter_model: Optional[str] = None,
) -> dict:
    start = time.time()
    # load manifest
    data_dir = os.getenv("DATA_DIR", "./data")
    manifest_file = os.getenv("MANIFEST_FILE", "submissions_manifest.jsonl")
    manifest_path = os.path.join(data_dir, manifest_file)
    results = []
    counts = {"processed": 0, "errors": 0, "no_text": 0}
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found at {manifest_path}")
    with open(manifest_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
                text = ""
                if s.get("has_body") and s.get("body_text"):
                    text = s.get("body_text", "")
                else:
                    # pick first parsable attachment
                    attachments = s.get("attachments", []) or []
                    for a in attachments:
                        sp = a.get("saved_path")
                        if not sp:
                            continue
                        lower = sp.lower()
                        if lower.endswith('.txt'):
                            text = read_text_from_file(sp) or ""
                            if text:
                                break
                        elif lower.endswith('.pdf'):
                            txt = read_text_from_file(sp)
                            if txt:
                                text = txt
                                break
                        elif lower.endswith('.docx'):
                            txt = read_text_from_file(sp)
                            if txt:
                                text = txt
                                break
                if not text:
                    counts["no_text"] += 1
                    results.append({
                        "course_id": course_id,
                        "assignment_id": assignment_id,
                        "user_id": s.get("user_id"),
                        "name": s.get("name"),
                        "reply": "",
                        "score": None,
                        "error": "no_text"
                    })
                    continue
                # call backend
                reply_text = ""
                backend_error = None
                try:
                    if backend == "ollama":
                        if not ollama_host or not ollama_model:
                            raise ValueError("Ollama host/model not provided")
                        resp = _call_ollama(ollama_host, ollama_model, prompt, text)
                        # Ollama returns messages list; find assistant content
                        if isinstance(resp, dict):
                            # Try common shapes
                            content = ""
                            if 'choices' in resp and resp['choices']:
                                content = resp['choices'][0].get('message', {}).get('content', '')
                            elif 'message' in resp:
                                content = resp.get('message', {}).get('content', '')
                            else:
                                content = json.dumps(resp)
                            reply_text = content
                    elif backend == "openrouter":
                        if not openrouter_api_key or not openrouter_model:
                            raise ValueError("OpenRouter key/model not provided")
                        resp = _call_openrouter(openrouter_api_key, openrouter_model, prompt, text)
                        # openrouter uses choices[].message.content
                        content = ""
                        if isinstance(resp, dict) and resp.get('choices'):
                            content = resp['choices'][0].get('message', {}).get('content', '')
                        else:
                            content = json.dumps(resp)
                        reply_text = content
                    else:
                        raise ValueError("Unknown backend")
                except Exception as e:
                    backend_error = str(e)

                # try to parse numeric score from reply_text (search for "/10" or "score: X")
                parsed_score = None
                if reply_text:
                    import re
                    m = re.search(r'([0-9]{1,3}(?:\.[0-9]+)?)\s*(?:/|of)?\s*10', reply_text)
                    if m:
                        try:
                            parsed_score = float(m.group(1))
                        except Exception:
                            parsed_score = None
                    else:
                        m2 = re.search(r'score[:\s\-]+([0-9]{1,3}(?:\.[0-9]+)?)', reply_text, re.I)
                        if m2:
                            try:
                                parsed_score = float(m2.group(1))
                            except Exception:
                                parsed_score = None

                result = {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "user_id": s.get("user_id"),
                    "name": s.get("name"),
                    "reply": reply_text,
                    "score": parsed_score,
                    "error": "backend_error" if backend_error else None
                }
                if backend_error:
                    counts["errors"] += 1
                else:
                    counts["processed"] += 1
                results.append(result)
            except Exception as e:
                counts["errors"] += 1
                results.append({
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "user_id": None,
                    "name": None,
                    "reply": "",
                    "score": None,
                    "error": f"internal_error: {e}"
                })
    # write results to out_path (jsonl)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fo:
        for r in results:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    elapsed = time.time() - start
    summary = {
        "counts": counts,
        "elapsed_secs": elapsed,
        "backend": backend,
        "out_path": out_path,
        "total": len(results)
    }
    return summary
