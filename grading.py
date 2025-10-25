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
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
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
    prompt: str,
    out_path: str,
    canvas_api_url: str,
    canvas_api_token: str,
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
