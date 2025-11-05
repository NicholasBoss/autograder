<<<<<<< HEAD
# grading.py
import os
import json
import time
import re
from typing import Literal, Optional, Dict
import requests
from pathlib import Path
from utils_text import read_text_from_file, extract_text_from_pdf_bytes, extract_text_from_docx_bytes

def _call_openrouter(api_key: str, model: str, system_prompt: str, user_text: str, timeout=60) -> Dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
=======
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
        if ext in (".txt", ".pdf", ".docx", ".html"):
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
>>>>>>> origin/Chase
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
<<<<<<< HEAD
            {"role": "user", "content": user_text}
        ],
        "max_tokens": 2048
    }
    r = requests.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _get_parsed_questions_content(course_id: str, assignment_id: str) -> Optional[str]:
    """Get the parsed questions content for a specific course and assignment."""
    base_download_dir = Path("./data/downloads")
    
    # Look for parsed questions in course-specific assignment folder
    if course_id == "unknown":
        # Handle legacy assignment folders
        assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    else:
        # Handle course-specific folders
        course_dir = base_download_dir / f"course_{course_id}"
        assignment_dir = course_dir / f"assignment_{assignment_id}"
    
    questions_dir = assignment_dir / "questions"
    
    if not questions_dir.exists():
        return None
    
    # Get all markdown files in the questions directory
    questions_files = [f for f in questions_dir.iterdir() if f.is_file() and f.suffix == '.md']
    
    if not questions_files:
        return None
    
    # Use the most recently modified file as the parsed questions
    questions_file = max(questions_files, key=lambda f: f.stat().st_mtime)
    
    try:
        with open(questions_file, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def grade_assignments(
    backend: Literal["openrouter"],
=======
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
>>>>>>> origin/Chase
    prompt: str,
    out_path: str,
    canvas_api_url: str,
    canvas_api_token: str,
<<<<<<< HEAD
    course_id,
    assignment_id,
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
    
    # Get parsed questions and answers
    parsed_questions_content = _get_parsed_questions_content(str(course_id), str(assignment_id))
    
    if not parsed_questions_content:
        print(f"⚠️  Warning: No parsed questions found for course {course_id}, assignment {assignment_id}")
        print("   Grading will proceed without answer key reference")
    else:
        print(f"✅ Found parsed questions and answers for comparison")
    
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
                        "score": 0,
                        "error": "no_text",
                        "feedback": "No submission text found"
                    })
                    continue
                
                # call backend with answer key comparison
                reply_text = ""
                score = None
                feedback = ""
                backend_error = None
                
                try:
                    if backend == "openrouter":
                        if not openrouter_api_key or not openrouter_model:
                            raise ValueError("OpenRouter key/model not provided")
                        
                        # Build the grading prompt with answer key reference
                        if parsed_questions_content:
                            system_prompt = f"""You are an expert grader evaluating student submissions against a provided answer key.

Your task is to:
1. Compare the student's submission against the expected answers
2. Determine if the student's answer is correct, partially correct, or incorrect
3. Provide a numerical score as a percentage (0-100)
4. Explain your reasoning

Be fair and flexible - accept answers that demonstrate understanding of the concepts, even if they're worded differently from the answer key.

ANSWER KEY AND EXPECTED ANSWERS:
{parsed_questions_content}

Evaluate the student's submission below and provide:
- A score (0-100)
- Brief feedback explaining the score"""
                        else:
                            system_prompt = prompt
                        
                        user_text = f"STUDENT SUBMISSION:\n{text}"
                        
                        resp = _call_openrouter(openrouter_api_key, openrouter_model, system_prompt, user_text)
                        
                        # Extract response content
                        content = ""
                        if isinstance(resp, dict) and resp.get('choices'):
                            content = resp['choices'][0].get('message', {}).get('content', '')
                        else:
                            content = json.dumps(resp)
                        
                        reply_text = content
                        
                        # Extract score from response
                        score = _extract_score_from_response(reply_text)
                        feedback = reply_text
                        
                    else:
                        raise ValueError("Unknown backend")
                        
                except Exception as e:
                    backend_error = str(e)
                    score = 0
                    feedback = f"Error during grading: {backend_error}"

                result = {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "user_id": s.get("user_id"),
                    "name": s.get("name"),
                    "reply": reply_text,
                    "score": score,
                    "feedback": feedback,
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
                    "score": 0,
                    "feedback": "",
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
        "total": len(results),
        "has_answer_key": parsed_questions_content is not None
    }
    return summary

def _extract_score_from_response(response_text: str) -> Optional[int]:
    """Extract a numeric score (0-100) from the LLM response."""
    # Try various patterns to find a score
    patterns = [
        r'score[:\s\-]+(\d{1,3})(?:\s*[/%])?',  # "score: 85" or "score: 85%"
        r'(\d{1,3})\s*(?:out of|/)\s*100',      # "85 out of 100" or "85/100"
        r'(\d{1,3})\s*%',                        # "85%"
        r'^(\d{1,3})$',                          # Just the number
    ]
    
    for pattern in patterns:
        match = re.search(pattern, response_text, re.IGNORECASE | re.MULTILINE)
        if match:
            try:
                score = int(match.group(1))
                # Clamp score between 0 and 100
                return max(0, min(100, score))
            except (ValueError, IndexError):
                continue
    
    # If no score found, return None
    return None
=======
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
    # Look for assignment-specific manifest first, then fall back to root manifest
    data_dir = env.get("DATA_DIR", "./data")
    manifest_name = env.get("MANIFEST_FILE", "submissions_manifest.jsonl")
    assignment_manifest = os.path.join(data_dir, "assignments", str(assignment_id), manifest_name)
    manifest_path = assignment_manifest if os.path.exists(assignment_manifest) else os.path.join(data_dir, manifest_name)
    submissions = _read_jsonl(manifest_path)
    _ensure_dir(out_path)

    # Clear old results file before grading starts
    if os.path.exists(out_path):
        os.remove(out_path)

    out_f = open(out_path, "w", encoding="utf-8")
    files = 0
    students = 0
    errors = 0

    # Load answer key text (any file type)
    # For HTML answer keys, check for pre-parsed version first
    chosen_answer_key_path = answer_key_path
    if not chosen_answer_key_path:
        ak_env = env.get("ANSWER_KEY_FILE")
        if ak_env:
            chosen_answer_key_path = os.path.join(env.get("DATA_DIR", "./data"), ak_env)
    
    answer_key_text = ""
    if chosen_answer_key_path:
        # If it's an HTML file, check for pre-parsed version
        if chosen_answer_key_path.lower().endswith('.html'):
            # For answerkey subfolder structure
            if "answerkey" in chosen_answer_key_path:
                parsed_path = os.path.join(os.path.dirname(chosen_answer_key_path), "answer_key_parsed.txt")
            else:
                parsed_path = os.path.splitext(chosen_answer_key_path)[0] + "_parsed.txt"
            
            if os.path.exists(parsed_path):
                answer_key_text = _read_file_text(parsed_path)
            else:
                answer_key_text = _read_file_text(chosen_answer_key_path)
        else:
            answer_key_text = _read_file_text(chosen_answer_key_path)
    
    print(f"[DEBUG] Answer key path: {chosen_answer_key_path}")
    print(f"[DEBUG] Answer key text length: {len(answer_key_text)}")

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
                # For HTML files, check for parsed version first
                if path.lower().endswith('.html'):
                    parsed_path = os.path.splitext(path)[0] + "_parsed.txt"
                    if os.path.exists(parsed_path):
                        t = read_text_from_file(parsed_path)
                    else:
                        t = read_text_from_file(path)
                else:
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

        print(f"[DEBUG] Grading student {sub.get('name')} - submission text length: {len(text)}")
        try:
            user_payload = (
                f"ANSWER_KEY:\n{answer_key_text}\n\n"
                f"STUDENT_SUBMISSION:\n{text}\n\n"
                f"GUIDANCE:\n{prompt}"
            )
            if backend == "ollama":
                reply = _call_ollama(ollama_host or "http://localhost:11434", ollama_model or "llama3.1", system_prompt, user_payload)
            else:
                # Use model from environment or fallback to gpt-3.5-turbo
                model = openrouter_model if openrouter_model else "openai/gpt-3.5-turbo"
                print(f"[DEBUG] Using OpenRouter model: {model}")
                reply = _call_openrouter(openrouter_api_key or "", model, system_prompt, user_payload)
        except Exception as e:
            print(f"[DEBUG] Exception during grading: {str(e)}")
            reply = ""
        err = None
        if not reply:
            err = "backend_error"
            errors += 1
            print(f"[DEBUG] No reply from backend for {sub.get('name')}")
        # Try to parse JSON response for structured grading
        per_question = None
        score = None
        if reply:
            print(f"[DEBUG] Reply length: {len(reply)}")
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
                        print(f"[DEBUG] Parsed score: {score}")
            except Exception as e:
                print(f"[DEBUG] Exception parsing JSON: {str(e)}")
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
>>>>>>> origin/Chase
