<<<<<<< HEAD
# app.py
import os
import json
import time
import re
import uuid
from typing import Optional
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_from_directory, Response
from dotenv import load_dotenv, set_key, dotenv_values
from pathlib import Path
import requests
import typer
from grading import grade_assignments
from concurrent.futures import ThreadPoolExecutor, as_completed

APP = Flask(__name__, template_folder="templates", static_folder="static")
APP.secret_key = os.getenv("FLASK_SECRET", "dev_secret_key_change_me")
load_dotenv()
env_path = Path(".env")

# sensible defaults
DEFAULTS = {
    "CANVAS_API_URL": "https://canvas.instructure.com",
    "DATA_DIR": "./data",
    "MANIFEST_FILE": "submissions_manifest.jsonl",
    "RESULTS_FILE": "results.jsonl",
    "ANSWER_KEY_FILE": "answer_key.json",
    "CANVAS_DOWNLOAD_DIR": "./data/downloads",
    "OPENROUTER_MODEL": "meta-llama/llama-3.1-8b-instruct:free"
}

def ensure_data_files():
    data_dir = os.getenv("DATA_DIR", DEFAULTS["DATA_DIR"])
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.getenv("CANVAS_DOWNLOAD_DIR", DEFAULTS["CANVAS_DOWNLOAD_DIR"]), exist_ok=True)
    
    # Create empty JSONL files for manifest and results if missing
    manifest_file = os.path.join(data_dir, os.getenv("MANIFEST_FILE", DEFAULTS["MANIFEST_FILE"]))
    results_file = os.path.join(data_dir, os.getenv("RESULTS_FILE", DEFAULTS["RESULTS_FILE"]))
    
    for path in [manifest_file, results_file]:
        if not os.path.exists(path):
            open(path, 'a', encoding='utf-8').close()
    
    # Note: Answer key file is no longer auto-created since it can be any file type
    # Users will upload their own answer key files via the web interface

ensure_data_files()

def load_env():
    load_dotenv()
    env = dotenv_values(".env")
    # apply defaults
    for k, v in DEFAULTS.items():
        env.setdefault(k, os.getenv(k, v))
    return env

CONFIG = load_env()

# Progress tracking for grading sessions
GRADING_PROGRESS = {}  # Format: {session_id: {"total": N, "completed": N, "current_user": str, "results": []}}

# Helpers to call Canvas endpoints
def _canvas_get(path, params=None):
    base = CONFIG.get("CANVAS_API_URL", DEFAULTS["CANVAS_API_URL"]).rstrip('/')
    token = CONFIG.get("CANVAS_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{base}/api/v1/{path.lstrip('/')}"
    r = requests.get(url, headers=headers, params=params, timeout=30)
    return r

@APP.route("/")
def index():
    cfg = load_env()
    # If missing required canvas token redirect to setup
    if not cfg.get("CANVAS_API_TOKEN"):
        return redirect(url_for("setup"))
    return render_template("index.html")

@APP.route("/test-keys")
def test_keys():
    return {
        "canvas_token_found": bool(CONFIG.get("CANVAS_API_TOKEN")),
        "openrouter_key_found": bool(CONFIG.get("OPENROUTER_API_KEY"))
    }

@APP.route("/setup", methods=["GET", "POST"])
def setup():
    cfg = load_env()
    if request.method == "POST":
        # collect fields
        fields = [
            "CANVAS_API_URL", "CANVAS_API_TOKEN", "CANVAS_COURSE_ID", "CANVAS_ASSIGNMENT_ID",
            "DATA_DIR", "MANIFEST_FILE", "RESULTS_FILE", "ANSWER_KEY_FILE", "CANVAS_DOWNLOAD_DIR",
            "OPENROUTER_API_KEY", "OPENROUTER_MODEL"
        ]
        # write to .env
        for f in fields:
            val = request.form.get(f, "").strip()
            if val == "":
                # skip empty to preserve previous
                continue
            set_key(".env", f, val)
        # reload config
        global CONFIG
        CONFIG = load_env()
        flash("Saved configuration to .env", "success")
        return redirect(url_for("index"))
    # GET: render setup with current config
    return render_template("setup.html", config=cfg)

@APP.route("/submissions")
def submissions():
    cfg = load_env()
    return render_template("submissions.html", config=cfg)

# 268730
# 12039643

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe filesystem storage."""
    import re
    # Remove or replace problematic characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove control characters and other problematic characters
    filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '_', filename)
    # Limit length and strip whitespace
    filename = filename.strip()[:200]
    return filename or "unnamed_file"


def parse_questions_from_text(text: str) -> list:
    """Parse questions from text content. Supports various question formats."""
    if not text or not text.strip():
        return []
    
    questions = []
    
    # Pattern 1: Numbered questions (1., 2., etc.)
    numbered_pattern = r'(?:^|\n)\s*(\d+)\.\s*(.+?)(?=(?:\n\s*\d+\.)|(?:\n\s*$)|$)'
    numbered_matches = re.findall(numbered_pattern, text, re.MULTILINE | re.DOTALL)
    
    if numbered_matches:
        for num, content in numbered_matches:
            questions.append({
                "question_number": int(num),
                "content": content.strip(),
                "type": "numbered"
            })
    
    # Pattern 2: Question headers (Question 1:, Q1:, etc.)
    if not questions:
        question_pattern = r'(?:^|\n)\s*(?:Question|Q)\s*(\d+)[\s:]+(.+?)(?=(?:\n\s*(?:Question|Q)\s*\d+)|(?:\n\s*$)|$)'
        question_matches = re.findall(question_pattern, text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        
        if question_matches:
            for num, content in question_matches:
                questions.append({
                    "question_number": int(num),
                    "content": content.strip(),
                    "type": "question_header"
                })
    
    # Pattern 3: Letter-based questions (a), b), etc.)
    if not questions:
        letter_pattern = r'(?:^|\n)\s*([a-z])\)\s*(.+?)(?=(?:\n\s*[a-z]\))|(?:\n\s*$)|$)'
        letter_matches = re.findall(letter_pattern, text, re.MULTILINE | re.DOTALL)
        
        if letter_matches:
            for i, (letter, content) in enumerate(letter_matches, 1):
                questions.append({
                    "question_number": i,
                    "letter": letter,
                    "content": content.strip(),
                    "type": "lettered"
                })
    
    # Pattern 4: Hash-based questions (#1, #2, etc.)
    if not questions:
        hash_pattern = r'(?:^|\n)\s*#(\d+)\s*(.+?)(?=(?:\n\s*#\d+)|(?:\n\s*$)|$)'
        hash_matches = re.findall(hash_pattern, text, re.MULTILINE | re.DOTALL)
        
        if hash_matches:
            for num, content in hash_matches:
                questions.append({
                    "question_number": int(num),
                    "content": content.strip(),
                    "type": "hash"
                })
    
    # If no patterns match, treat entire text as one question
    if not questions:
        questions.append({
            "question_number": 1,
            "content": text.strip(),
            "type": "single"
        })
    
    return questions


def compare_question_answers(student_answer: str, correct_answer: str) -> dict:
    """Compare a student's answer to the correct answer."""
    if not student_answer or not correct_answer:
        return {
            "is_correct": False,
            "similarity_score": 0.0,
            "feedback": "Missing answer content"
        }
    
    # Normalize text for comparison
    def normalize_text(text):
        return re.sub(r'\s+', ' ', text.lower().strip())
    
    student_norm = normalize_text(student_answer)
    correct_norm = normalize_text(correct_answer)
    
    # Exact match
    if student_norm == correct_norm:
        return {
            "is_correct": True,
            "similarity_score": 1.0,
            "feedback": "Perfect match"
        }
    
    # Substring match
    if correct_norm in student_norm or student_norm in correct_norm:
        return {
            "is_correct": True,
            "similarity_score": 0.8,
            "feedback": "Partial match - answer contains correct information"
        }
    
    # Word overlap scoring
    student_words = set(student_norm.split())
    correct_words = set(correct_norm.split())
    
    if len(correct_words) == 0:
        similarity = 0.0
    else:
        overlap = student_words.intersection(correct_words)
        similarity = len(overlap) / len(correct_words)
    
    is_correct = similarity >= 0.6  # 60% word overlap threshold
    
    return {
        "is_correct": is_correct,
        "similarity_score": similarity,
        "feedback": f"Word overlap: {similarity:.2%} ({'Correct' if is_correct else 'Incorrect'})"
    }


def get_canvas_assignments(course_id: str = None, file_uploads_only: bool = False) -> list:
    """Fetch all assignments for a course from Canvas API with pagination support."""
    cfg = load_env()
    api_url = cfg.get("CANVAS_API_URL")
    api_token = cfg.get("CANVAS_API_TOKEN")
    canvas_course_id = course_id or cfg.get("CANVAS_COURSE_ID")
    
    if not (api_url and api_token and canvas_course_id):
        print("Missing Canvas API configuration")
        return []
    
    headers = {"Authorization": f"Bearer {api_token}"}
    all_assignments = []
    current_url = f"{api_url.rstrip('/')}/api/v1/courses/{canvas_course_id}/assignments"
    page_num = 1
    
    # Add per_page parameter for better performance
    params = {"per_page": 100}
    
    try:
        while current_url:
            print(f"Fetching assignments page {page_num}...")
            
            # For first request, use params; for subsequent requests, URL already has params
            request_params = params if current_url == f"{api_url.rstrip('/')}/api/v1/courses/{canvas_course_id}/assignments" else None
            
            resp = requests.get(current_url, headers=headers, params=request_params, timeout=30)
            if resp.status_code != 200:
                print(f"Failed to fetch assignments: {resp.status_code} {resp.text}")
                if not all_assignments:  # Return error only if we got no data
                    return []
                break
            
            assignments = resp.json()
            if not isinstance(assignments, list):
                assignments = assignments.get('assignments', [])
            
            # Filter for file upload assignments if requested
            if file_uploads_only:
                filtered_assignments = []
                for assignment in assignments:
                    submission_types = assignment.get('submission_types', [])
                    # Check for file upload submission types
                    if any(sub_type in ['online_upload', 'media_recording'] for sub_type in submission_types):
                        filtered_assignments.append(assignment)
                all_assignments.extend(filtered_assignments)
            else:
                all_assignments.extend(assignments)
            
            print(f"  Retrieved {len(assignments)} assignments (filtered: {len(filtered_assignments) if file_uploads_only else len(assignments)}, total: {len(all_assignments)})")
            
            # Parse Link header for next page
            link_header = resp.headers.get('Link', '')
            links = parse_link_header(link_header)
            current_url = links.get('next')
            page_num += 1
            
            # Small delay to be respectful to the API
            time.sleep(0.2)
        
        # Sort by due date (most recent first) or by name if no due date
        all_assignments.sort(key=lambda a: a.get('due_at') or a.get('name', ''), reverse=True)
        print(f"✅ Retrieved {len(all_assignments)} total assignments" + (" with file uploads" if file_uploads_only else ""))
        return all_assignments
        
    except Exception as e:
        print(f"Error fetching assignments: {e}")
        return []


def get_parsed_questions_content_with_course(course_id: str, assignment_id: str) -> str:
    """Get the parsed questions content for a specific course and assignment (markdown format)."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
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
        print(f"No questions directory found for course {course_id}, assignment {assignment_id}")
        return None
    
    # Get all markdown files in the questions directory
    questions_files = [f for f in questions_dir.iterdir() if f.is_file() and f.suffix == '.md']
    
    if not questions_files:
        print(f"No parsed questions files found for course {course_id}, assignment {assignment_id}")
        return None
    
    # Use the most recently modified file as the parsed questions
    questions_file = max(questions_files, key=lambda f: f.stat().st_mtime)
    
    try:
        with open(questions_file, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # Try reading as binary and decode
        try:
            with open(questions_file, 'rb') as f:
                content = f.read()
                return content.decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading parsed questions as binary: {e}")
            return None
    except Exception as e:
        print(f"Error reading parsed questions: {e}")
        return None

def get_parsed_questions_content(assignment_id: str) -> str:
    """Get the parsed questions content for a specific assignment (markdown format) - legacy support."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Look for parsed questions in assignment-specific folder
    assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    questions_dir = assignment_dir / "questions"
    
    if not questions_dir.exists():
        print(f"No questions directory found for assignment {assignment_id}")
        return None
    
    # Get all markdown files in the questions directory
    questions_files = [f for f in questions_dir.iterdir() if f.is_file() and f.suffix == '.md']
    
    if not questions_files:
        print(f"No parsed questions files found for assignment {assignment_id}")
        return None
    
    # Use the most recently modified file as the parsed questions
    questions_file = max(questions_files, key=lambda f: f.stat().st_mtime)
    
    try:
        with open(questions_file, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # Try reading as binary and decode
        try:
            with open(questions_file, 'rb') as f:
                content = f.read()
                return content.decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading parsed questions as binary: {e}")
            return None
    except Exception as e:
        print(f"Error reading parsed questions: {e}")
        return None

def get_answer_key_content(assignment_id: str) -> str:
    """Get the answer key content for a specific assignment."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Look for answer key in assignment-specific folder
    assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    answer_key_dir = assignment_dir / "answer_key"
    
    if not answer_key_dir.exists():
        print(f"No answer key directory found for assignment {assignment_id}")
        return None
    
    # Get all files in the answer key directory
    answer_key_files = [f for f in answer_key_dir.iterdir() if f.is_file()]
    
    if not answer_key_files:
        print(f"No answer key files found for assignment {assignment_id}")
        return None
    
    # Use the most recently modified file as the answer key
    answer_key_file = max(answer_key_files, key=lambda f: f.stat().st_mtime)
    
    try:
        with open(answer_key_file, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # Try reading as binary and decode
        try:
            with open(answer_key_file, 'rb') as f:
                content = f.read()
                return content.decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"Error reading answer key as binary: {e}")
            return None
    except Exception as e:
        print(f"Error reading answer key: {e}")
        return None


def parse_link_header(link_header: str) -> dict:
    """Parse Canvas API Link header to extract pagination URLs."""
    links = {}
    if not link_header:
        return links
    
    # Split by comma and parse each link
    for part in link_header.split(','):
        part = part.strip()
        if '; rel=' not in part:
            continue
        
        url_part, rel_part = part.split('; rel=', 1)
        url = url_part.strip('<> ')
        rel = rel_part.strip('"')
        links[rel] = url
    
    return links


def download_attachment(session: requests.Session, url: str, save_path: Path) -> tuple:
    """Download an attachment file from Canvas."""
    try:
        # Ensure parent directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download with streaming to handle large files
        resp = session.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        
        with open(save_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        return True, None
    except Exception as e:
        return False, str(e)

@APP.route("/fetch_submissions", methods=["POST"])
def fetch_submissions():
    """Fetch all submissions for a given course and assignment with pagination and file downloads."""
    data = request.get_json()
    course_id = data.get("course_id")
    assignment_id = data.get("assignment_id")
    download_files = data.get("download_files", True)

    if not course_id or not assignment_id:
        return jsonify({"error": "course_id and assignment_id are required"}), 400

    cfg = load_env()
    base_url = f"{cfg.get('CANVAS_API_URL').rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions"
    headers = {"Authorization": f"Bearer {cfg.get('CANVAS_API_TOKEN')}"}
    
    # Set up directories with course and assignment-specific folders
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    course_dir = base_download_dir / f"course_{course_id}"
    download_dir = course_dir / f"assignment_{assignment_id}"
    answer_key_dir = download_dir / "answer_key"
    questions_dir = download_dir / "questions"
    data_dir = Path(cfg.get("DATA_DIR", "./data"))
    manifest_path = data_dir / f"submissions_manifest_course_{course_id}_assignment_{assignment_id}.jsonl"
    
    download_dir.mkdir(parents=True, exist_ok=True)
    answer_key_dir.mkdir(parents=True, exist_ok=True)
    questions_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    params = {
        "include[]": ["attachments", "user"],
        "per_page": 100
    }

    all_submissions = []
    current_url = base_url
    page_num = 1
    
    try:
        print(f"📂 Creating assignment folder: {download_dir}")
        print(f"� Creating answer_key folder: {answer_key_dir}")
        print(f"📁 Creating questions folder: {questions_dir}")
        print(f"�📄 Manifest will be saved as: {manifest_path.name}")
        
        # Fetch all submissions with pagination
        while current_url:
            print(f"Fetching page {page_num} from Canvas API...")
            
            # For first request, use params; for subsequent requests, URL already has params
            request_params = params if current_url == base_url else None
            
            resp = requests.get(current_url, headers=headers, params=request_params, timeout=60)
            resp.raise_for_status()

            
            submissions = resp.json()
            if not isinstance(submissions, list):
                submissions = submissions.get('submissions', [])
            
            all_submissions.extend(submissions)
            print(f"  Retrieved {len(submissions)} submissions (total: {len(all_submissions)})")

            
            # Parse Link header for next page
            link_header = resp.headers.get('Link', '')
            links = parse_link_header(link_header)
            current_url = links.get('next')
            page_num += 1
            
            # Small delay to be respectful to the API
            time.sleep(0.5)

        print(f"✅ Retrieved {len(all_submissions)} total submissions.")

        # Process submissions and handle downloads
        manifest_entries = []
        total_downloads = 0
        failed_downloads = 0
        
        session = requests.Session()
        session.headers.update(headers)

        for submission in all_submissions:
            user = submission.get("user") or {}
            user_id = str(user.get("id", submission.get("user_id", "unknown")))
            user_name = user.get("name", user.get("display_name", f"User_{user_id}"))
            
            # Process attachments
            attachments_info = []
            attachments = submission.get("attachments") or []
            
            for attachment in attachments:
                canvas_file_id = attachment.get("id")
                original_filename = attachment.get("filename", attachment.get("display_name", "unnamed_file"))
                download_url = attachment.get("url")
                content_type = attachment.get("content-type", attachment.get("content_type", "application/octet-stream"))
                file_size = attachment.get("size", 0)
                
                # Create safe filename
                safe_filename = sanitize_filename(f"user_{user_id}_{canvas_file_id}_{original_filename}")
                save_path = download_dir / safe_filename
                
                download_success = False
                download_error = None
                
                if download_files and download_url:
                    print(f"  Downloading: {original_filename} -> {safe_filename}")
                    download_success, download_error = download_attachment(session, download_url, save_path)
                    
                    if download_success:
                        total_downloads += 1
                    else:
                        failed_downloads += 1
                        print(f"    Failed: {download_error}")
                    
                    # Small delay between downloads
                    time.sleep(0.2)
                
                attachments_info.append({
                    "canvas_file_id": canvas_file_id,
                    "original_filename": original_filename,
                    "saved_path": str(save_path) if download_success else None,
                    "content_type": content_type,
                    "size": file_size,
                    "download_success": download_success,
                    "download_error": download_error
                })
            
            # Create manifest entry
            manifest_entry = {
                "course_id": course_id,
                "assignment_id": assignment_id,
                "user_id": user_id,
                "user_name": user_name,
                "attempt": submission.get("attempt", 1),
                "workflow_state": submission.get("workflow_state"),
                "submitted_at": submission.get("submitted_at"),
                "score": submission.get("score"),
                "grade": submission.get("grade"),
                "has_body": bool(submission.get("body")),
                "body_text": submission.get("body", ""),
                "attachments": attachments_info,
                "attachment_count": len(attachments_info)
            }
            
            manifest_entries.append(manifest_entry)
            
            if attachments_info:
                print(f"Processed user ({user_id}): {len(attachments_info)} attachment(s)")

        # Write manifest file
        with open(manifest_path, 'w', encoding='utf-8') as f:
            for entry in manifest_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        # Return summary
        summary = {
            "success": True,
            "total_students": len(manifest_entries),
            "total_submissions": len(all_submissions),
            "total_downloads": total_downloads,
            "failed_downloads": failed_downloads,
            "manifest_file": str(manifest_path),
            "download_directory": str(download_dir),
            "submissions": [
                {
                    "user_id": entry["user_id"],
                    "user_name": entry["user_name"],
                    "attachment_count": entry["attachment_count"],
                    "workflow_state": entry["workflow_state"],
                    "has_body": entry["has_body"]
                }
                for entry in manifest_entries
            ]
        }

        print(f"📊 Students: {summary['total_students']}")
        print(f"📁 Files downloaded: {summary['total_downloads']}")
        print(f"❌ Failed downloads: {summary['failed_downloads']}")
        print(f"� Assignment folder: {download_dir}")
        print(f"�📄 Manifest file: {manifest_path}")

        return jsonify(summary)

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

@APP.route("/get_feedback", methods=["POST"])
def get_feedback():
    """Send submission text to OpenRouter for feedback"""
    data = request.get_json()
    submission_text = data.get("submission", "")
    prompt = f"Provide constructive, helpful feedback for the following student submission:\n\n{submission_text}"

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}]
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {CONFIG.get('OPENROUTER_API_KEY')}", "Content-Type": "application/json"},
        json=payload
    )

    if response.status_code != 200:
        return jsonify({"error": response.text}), response.status_code

    feedback = response.json()["choices"][0]["message"]["content"]
    return jsonify({"feedback": feedback})

@APP.route("/api/canvas/validate", methods=["GET"])
def api_canvas_validate():
    api_url = request.args.get('api_url')
    token = request.args.get('token')
    
    if api_url and token:
        # Use provided parameters for validation
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = requests.get(f"{api_url.rstrip('/')}/users/self", headers=headers, timeout=30)
            if r.status_code == 200:
                return jsonify({"ok": True, "user": r.json()})
            else:
                return jsonify({"ok": False, "status": r.status_code, "text": r.text}), 400
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    else:
        # Fall back to config-based validation
        cfg = load_env()
        r = _canvas_get("users/self")
        if r.status_code == 200:
            return jsonify({"ok": True, "user": r.json()})
        else:
            return jsonify({"ok": False, "status": r.status_code, "text": r.text}), 400

@APP.route("/api/canvas/validate", methods=["POST"])
def validate_canvas_token():
    """Validate Canvas API token by calling /users/self."""
    data = request.get_json()
    api_url = data.get("CANVAS_API_URL")
    api_token = data.get("CANVAS_API_TOKEN")

    if not api_url or not api_token:
        return jsonify({"ok": False, "error": "Missing Canvas URL or token"}), 400

    try:
        resp = requests.get(
            f"{api_url.rstrip('/')}/api/v1/users/self",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            user = resp.json()
            return jsonify({"ok": True, "user": user})
        else:
            return jsonify({
                "ok": False,
                "error": f"Invalid token (status {resp.status_code})"
            }), 401
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@APP.route("/api/canvas/courses", methods=["GET"])
def api_canvas_courses():
    api_url = request.args.get('api_url')
    token = request.args.get('token')
    
    if api_url and token:
        # Use provided parameters
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = requests.get(f"{api_url.rstrip('/')}/courses", headers=headers, timeout=30)
            if r.status_code == 200:
                return jsonify(r.json())
            return jsonify({"error": r.text}), r.status_code
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # Fall back to config-based API call
        r = _canvas_get("courses")
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({"error": r.text}), r.status_code

@APP.route("/api/canvas/<int:course_id>/assignments", methods=["GET"])
def api_canvas_assignments(course_id):
    api_url = request.args.get('api_url')
    token = request.args.get('token')
    file_uploads_only = request.args.get('file_uploads_only', 'false').lower() == 'true'
    
    if api_url and token:
        # Use provided parameters with pagination support
        headers = {"Authorization": f"Bearer {token}"}
        all_assignments = []
        current_url = f"{api_url.rstrip('/')}/courses/{course_id}/assignments"
        page_num = 1
        
        # Add per_page parameter for better performance
        params = {"per_page": 100}
        
        try:
            while current_url:
                print(f"Fetching assignments page {page_num}...")
                
                # For first request, use params; for subsequent requests, URL already has params
                request_params = params if current_url == f"{api_url.rstrip('/')}/courses/{course_id}/assignments" else None
                
                r = requests.get(current_url, headers=headers, params=request_params, timeout=30)
                if r.status_code != 200:
                    return jsonify({"error": r.text}), r.status_code
                
                assignments = r.json()
                if not isinstance(assignments, list):
                    assignments = assignments.get('assignments', [])
                
                # Filter for file upload assignments if requested
                if file_uploads_only:
                    filtered_assignments = []
                    for assignment in assignments:
                        submission_types = assignment.get('submission_types', [])
                        # Check for file upload submission types
                        if any(sub_type in ['online_upload', 'media_recording'] for sub_type in submission_types):
                            filtered_assignments.append(assignment)
                    all_assignments.extend(filtered_assignments)
                else:
                    all_assignments.extend(assignments)
                
                print(f"  Retrieved {len(assignments)} assignments (filtered: {len(filtered_assignments) if file_uploads_only else len(assignments)}, total: {len(all_assignments)})")
                
                # Parse Link header for next page
                link_header = r.headers.get('Link', '')
                links = parse_link_header(link_header)
                current_url = links.get('next')
                page_num += 1
                
                # Small delay to be respectful to the API
                time.sleep(0.2)
            
            print(f"✅ Retrieved {len(all_assignments)} total assignments" + (" with file uploads" if file_uploads_only else ""))
            return jsonify(all_assignments)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # Fall back to config-based API call with pagination
        all_assignments = []
        current_url = None
        page_num = 1
        
        try:
            while True:
                if current_url:
                    # Use the full URL from pagination
                    r = requests.get(current_url, timeout=30)
                else:
                    # First request using helper function
                    r = _canvas_get(f"courses/{course_id}/assignments", {"per_page": 100})
                
                if r.status_code != 200:
                    if not all_assignments:  # Return error only if we got no data
                        return jsonify({"error": r.text}), r.status_code
                    break
                
                assignments = r.json()
                if not isinstance(assignments, list):
                    assignments = assignments.get('assignments', [])
                
                # Filter for file upload assignments if requested
                if file_uploads_only:
                    filtered_assignments = []
                    for assignment in assignments:
                        submission_types = assignment.get('submission_types', [])
                        # Check for file upload submission types
                        if any(sub_type in ['online_upload', 'media_recording'] for sub_type in submission_types):
                            filtered_assignments.append(assignment)
                    all_assignments.extend(filtered_assignments)
                else:
                    all_assignments.extend(assignments)
                
                # Parse Link header for next page
                link_header = r.headers.get('Link', '')
                links = parse_link_header(link_header)
                current_url = links.get('next')
                
                if not current_url:
                    break
                    
                page_num += 1
                time.sleep(0.2)
            
            return jsonify(all_assignments)
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@APP.route("/api/canvas/assignments", methods=["GET"])
def api_get_assignments():
    """Get assignments from Canvas for the configured course."""
    assignments = get_canvas_assignments()
    if not assignments:
        return jsonify({"error": "Could not fetch assignments"}), 400
    
    # Format assignments for dropdown/selection
    formatted_assignments = []
    for assignment in assignments:
        formatted_assignments.append({
            "id": assignment.get("id"),
            "name": assignment.get("name"),
            "due_at": assignment.get("due_at"),
            "points_possible": assignment.get("points_possible"),
            "published": assignment.get("published", False)
        })
    
    return jsonify(formatted_assignments)

@APP.route("/api/refresh", methods=["GET"])
def api_refresh():
    # reload local files into memory (simple)
    global CONFIG
    CONFIG = load_env()
    ensure_data_files()
    return jsonify({"ok": True})

@APP.route("/upload/answer-key", methods=["GET", "POST"])
def upload_answer_key():
    """Upload and save answer key file to assignment-specific answer_key folder."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    if request.method == "POST":
        uploaded_file = request.files.get("answer_key_file")
        # Get course and assignment IDs
        course_id = request.form.get("course_id", "").strip()
        assignment_id = request.form.get("assignment_id", "").strip()
        
        if not uploaded_file or uploaded_file.filename == '':
            return jsonify({"success": False, "error": "No file selected for upload"}), 400
        
        if not assignment_id:
            return jsonify({"success": False, "error": "Assignment ID is required"}), 400
        
        if not course_id:
            return jsonify({"success": False, "error": "Course ID is required"}), 400
        
        # Create course and assignment-specific answer key directory and questions directory
        course_dir = base_download_dir / f"course_{course_id}"
        assignment_dir = course_dir / f"assignment_{assignment_id}"
        answer_key_dir = assignment_dir / "answer_key"
        questions_dir = assignment_dir / "questions"
        answer_key_dir.mkdir(parents=True, exist_ok=True)
        questions_dir.mkdir(parents=True, exist_ok=True)
        
        # Use the original filename directly
        original_filename = uploaded_file.filename
        # Sanitize the filename for safe storage
        safe_filename = sanitize_filename(original_filename)
        key_file = answer_key_dir / safe_filename
        
        try:
            # Save the file directly without JSON parsing
            uploaded_file.seek(0)  # Reset file pointer
            with open(key_file, "wb") as fo:
                fo.write(uploaded_file.read())
            
            print(f"✅ Answer key saved to: {key_file}")
            
            return jsonify({
                "success": True, 
                "message": f"Answer key successfully uploaded",
                "course_id": course_id,
                "assignment_id": assignment_id,
                "filename": safe_filename,
                "file_path": str(key_file)
            })
            
        except UnicodeDecodeError:
            return jsonify({"success": False, "error": "File encoding error"}), 400
        except Exception as e:
            return jsonify({"success": False, "error": f"Error processing file: {str(e)}"}), 500
    
    # GET request - show upload form
    # Look for existing answer key files across all assignments
    existing_answer_keys = []
    
    try:
        if base_download_dir.exists():
            # Scan course-based folder structure
            for course_folder in base_download_dir.iterdir():
                if course_folder.is_dir() and course_folder.name.startswith("course_"):
                    course_id = course_folder.name.replace("course_", "")
                    
                    for assignment_folder in course_folder.iterdir():
                        if assignment_folder.is_dir() and assignment_folder.name.startswith("assignment_"):
                            assignment_id = assignment_folder.name.replace("assignment_", "")
                            answer_key_dir = assignment_folder / "answer_key"
                            
                            if answer_key_dir.exists():
                                for key_file in answer_key_dir.iterdir():
                                    if key_file.is_file():
                                        try:
                                            stat = key_file.stat()
                                            
                                            # Check if questions have been parsed for this answer key
                                            questions_dir = assignment_folder / "questions"
                                            parsed_questions_file = questions_dir / f"parsed_questions_{key_file.name}.md"
                                            has_parsed_questions = parsed_questions_file.exists()
                                            
                                            existing_answer_keys.append({
                                                "course_id": course_id,
                                                "assignment_id": assignment_id,
                                                "filename": key_file.name,
                                                "size": stat.st_size,
                                                "modified": time.ctime(stat.st_mtime),
                                                "path": str(key_file),
                                                "has_parsed_questions": has_parsed_questions,
                                                "parsed_questions_path": str(parsed_questions_file) if has_parsed_questions else None
                                            })
                                        except Exception as e:
                                            print(f"Error reading answer key file {key_file}: {e}")
            
            # Also scan legacy assignment folders (without course prefix) for backward compatibility
            for assignment_folder in base_download_dir.iterdir():
                if assignment_folder.is_dir() and assignment_folder.name.startswith("assignment_"):
                    assignment_id = assignment_folder.name.replace("assignment_", "")
                    answer_key_dir = assignment_folder / "answer_key"
                    
                    if answer_key_dir.exists():
                        for key_file in answer_key_dir.iterdir():
                            if key_file.is_file():
                                try:
                                    stat = key_file.stat()
                                    
                                    # Check if questions have been parsed for this answer key
                                    questions_dir = assignment_folder / "questions"
                                    parsed_questions_file = questions_dir / f"parsed_questions_{key_file.name}.md"
                                    has_parsed_questions = parsed_questions_file.exists()
                                    
                                    existing_answer_keys.append({
                                        "course_id": "unknown",
                                        "assignment_id": assignment_id,
                                        "filename": key_file.name,
                                        "size": stat.st_size,
                                        "modified": time.ctime(stat.st_mtime),
                                        "path": str(key_file),
                                        "has_parsed_questions": has_parsed_questions,
                                        "parsed_questions_path": str(parsed_questions_file) if has_parsed_questions else None,
                                        "legacy": True
                                    })
                                except Exception as e:
                                    print(f"Error reading answer key file {key_file}: {e}")
    except Exception as e:
        print(f"Error scanning for existing answer keys: {e}")
    
    # Sort by modification time (newest first)
    existing_answer_keys.sort(key=lambda x: Path(x["path"]).stat().st_mtime, reverse=True)
    
    # Get available assignments from Canvas
    assignments = get_canvas_assignments()
    
    return render_template("upload_answer_key.html", existing_answer_keys=existing_answer_keys, assignments=assignments)

@APP.route("/api/parse-questions/<assignment_id>/<filename>", methods=["POST"])
def parse_questions_with_openrouter(assignment_id, filename):
    """Parse questions from answer key using OpenRouter API."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct paths
    assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    answer_key_dir = assignment_dir / "answer_key"
    questions_dir = assignment_dir / "questions"
    key_file = answer_key_dir / filename
    
    if not key_file.exists():
        return jsonify({"error": "Answer key file not found"}), 404
    
    # Create questions directory if it doesn't exist
    questions_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Read the answer key content
        with open(key_file, 'r', encoding='utf-8') as f:
            answer_key_content = f.read()
    except UnicodeDecodeError:
        # Try reading as binary and decode
        try:
            with open(key_file, 'rb') as f:
                content = f.read()
                answer_key_content = content.decode('utf-8', errors='ignore')
        except Exception as e:
            return jsonify({"error": f"Error reading answer key file: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error reading answer key file: {str(e)}"}), 500
    
    # Create prompt for OpenRouter to return markdown format
    prompt = f"""Please analyze the following answer key content and extract individual questions with their answers. 

Format the output as clean markdown with numbered questions. Each question should be clearly separated with proper markdown formatting.

Answer Key Content:
{answer_key_content}

Please format your response as markdown:

## Question 1
**Question:** [Question text here]

**Answer:** [Complete answer here]

## Question 2
**Question:** [Question text here]

**Answer:** [Complete answer here]

Continue this pattern for all questions found. Use proper markdown formatting with headers, bold text, and clear separation between questions."""

    # Call OpenRouter API
    openrouter_api_key = cfg.get("OPENROUTER_API_KEY")
    openrouter_model = cfg.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
    
    if not openrouter_api_key:
        return jsonify({"error": "OpenRouter API key not configured"}), 400
    
    try:
        payload = {
            "model": openrouter_model,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"OpenRouter API error: {response.text}"}), response.status_code
        
        parsed_questions = response.json()["choices"][0]["message"]["content"]
        
        # Save parsed questions to markdown file
        questions_filename = f"parsed_questions_{filename}.md"
        questions_file = questions_dir / questions_filename
        
        with open(questions_file, 'w', encoding='utf-8') as f:
            f.write(f"# Parsed Questions\n\n")
            f.write(f"**Source:** {filename}  \n")
            f.write(f"**Assignment ID:** {assignment_id}  \n")
            f.write(f"**Parsed on:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
            f.write("---\n\n")
            f.write(parsed_questions)
        
        return jsonify({
            "success": True,
            "message": f"Questions parsed and saved to {questions_filename}",
            "questions_file": str(questions_file),
            "parsed_content": parsed_questions
        })
        
    except Exception as e:
        return jsonify({"error": f"Error parsing questions: {str(e)}"}), 500

@APP.route("/api/parse-questions/<course_id>/<assignment_id>/<filename>", methods=["POST"])
def parse_questions_with_openrouter_course(course_id, assignment_id, filename):
    """Parse questions from answer key using OpenRouter API with course structure."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct paths for course structure
    course_dir = base_download_dir / f"course_{course_id}"
    assignment_dir = course_dir / f"assignment_{assignment_id}"
    answer_key_dir = assignment_dir / "answer_key"
    questions_dir = assignment_dir / "questions"
    key_file = answer_key_dir / filename
    
    if not key_file.exists():
        return jsonify({"error": "Answer key file not found"}), 404
    
    # Create questions directory if it doesn't exist
    questions_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Read the answer key content
        with open(key_file, 'r', encoding='utf-8') as f:
            answer_key_content = f.read()
    except UnicodeDecodeError:
        # Try reading as binary and decode
        try:
            with open(key_file, 'rb') as f:
                content = f.read()
                answer_key_content = content.decode('utf-8', errors='ignore')
        except Exception as e:
            return jsonify({"error": f"Error reading answer key file: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Error reading answer key file: {str(e)}"}), 500
    
    # Create prompt for OpenRouter to return markdown format
    prompt = f"""Please analyze the following answer key content and extract individual questions with their answers. 

Format the output as clean markdown with numbered questions. Each question should be clearly separated with proper markdown formatting.

Answer Key Content:
{answer_key_content}

Please format your response as markdown:

## Question 1
**Question:** [Question text here]

**Answer:** [Complete answer here]

## Question 2
**Question:** [Question text here]

**Answer:** [Complete answer here]

Continue this pattern for all questions found. Use proper markdown formatting with headers, bold text, and clear separation between questions."""

    # Call OpenRouter API
    openrouter_api_key = cfg.get("OPENROUTER_API_KEY")
    openrouter_model = cfg.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
    
    if not openrouter_api_key:
        return jsonify({"error": "OpenRouter API key not configured"}), 400
    
    try:
        payload = {
            "model": openrouter_model,
            "messages": [{"role": "user", "content": prompt}]
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"OpenRouter API error: {response.text}"}), response.status_code
        
        parsed_questions = response.json()["choices"][0]["message"]["content"]
        
        # Save parsed questions to markdown file
        questions_filename = f"parsed_questions_{filename}.md"
        questions_file = questions_dir / questions_filename
        
        with open(questions_file, 'w', encoding='utf-8') as f:
            f.write(f"# Parsed Questions\n\n")
            f.write(f"**Source:** {filename}  \n")
            f.write(f"**Course ID:** {course_id}  \n")
            f.write(f"**Assignment ID:** {assignment_id}  \n")
            f.write(f"**Parsed on:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
            f.write("---\n\n")
            f.write(parsed_questions)
        
        return jsonify({
            "success": True,
            "message": f"Questions parsed and saved to {questions_filename}",
            "course_id": course_id,
            "assignment_id": assignment_id,
            "questions_file": str(questions_file),
            "parsed_content": parsed_questions
        })
        
    except Exception as e:
        return jsonify({"error": f"Error parsing questions: {str(e)}"}), 500

@APP.route("/download/answer-key/<assignment_id>/<filename>")
def download_answer_key(assignment_id, filename):
    """Download a specific answer key file."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct path to answer key file
    assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    answer_key_dir = assignment_dir / "answer_key"
    key_file = answer_key_dir / filename
    
    if not key_file.exists():
        flash("Answer key file not found", "danger")
        return redirect(url_for("upload_answer_key"))
    
    try:
        file_ext = key_file.suffix or ".txt"
        return send_from_directory(
            directory=str(answer_key_dir),
            path=filename,
            as_attachment=True,
            download_name=f"answer_key_assignment_{assignment_id}_{time.strftime('%Y%m%d_%H%M%S')}{file_ext}"
        )
    except Exception as e:
        flash(f"Error downloading file: {str(e)}", "danger")
        return redirect(url_for("upload_answer_key"))

@APP.route("/download/answer-key/<course_id>/<assignment_id>/<filename>")
def download_answer_key_with_course(course_id, assignment_id, filename):
    """Download a specific answer key file with course structure."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct path to answer key file in course structure
    course_dir = base_download_dir / f"course_{course_id}"
    assignment_dir = course_dir / f"assignment_{assignment_id}"
    answer_key_dir = assignment_dir / "answer_key"
    key_file = answer_key_dir / filename
    
    if not key_file.exists():
        flash("Answer key file not found", "danger")
        return redirect(url_for("upload_answer_key"))
    
    try:
        file_ext = key_file.suffix or ".txt"
        return send_from_directory(
            directory=str(answer_key_dir),
            path=filename,
            as_attachment=True,
            download_name=f"answer_key_course_{course_id}_assignment_{assignment_id}_{time.strftime('%Y%m%d_%H%M%S')}{file_ext}"
        )
    except Exception as e:
        flash(f"Error downloading file: {str(e)}", "danger")
        return redirect(url_for("upload_answer_key"))

@APP.route("/api/available-courses", methods=["GET"])
def api_get_available_courses():
    """Get list of courses that have assignments with data, with course names from Canvas."""
    try:
        cfg = load_env()
        base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
        courses = []
        course_map = {}  # Store by course_id for deduplication
        
        # Try to fetch course names from Canvas
        canvas_courses_map = {}
        try:
            api_url = cfg.get("CANVAS_API_URL", DEFAULTS["CANVAS_API_URL"])
            api_token = cfg.get("CANVAS_API_TOKEN", "")
            if api_url and api_token:
                headers = {"Authorization": f"Bearer {api_token}"}
                resp = requests.get(f"{api_url.rstrip('/')}/api/v1/courses", headers=headers, timeout=10, params={"per_page": 100})
                if resp.status_code == 200:
                    for course in resp.json():
                        course_id = str(course.get("id", ""))
                        # Use only the original course name (not nickname)
                        course_name = course.get("name") or course.get("course_code", f"Course {course_id}")
                        canvas_courses_map[course_id] = course_name
        except Exception as canvas_err:
            print(f"Note: Could not fetch Canvas courses: {canvas_err}")
        
        if base_download_dir.exists():
            for course_folder in base_download_dir.iterdir():
                if course_folder.is_dir() and course_folder.name.startswith("course_"):
                    course_id = course_folder.name.replace("course_", "")
                    
                    # Count assignments in this course
                    assignment_count = 0
                    for item in course_folder.iterdir():
                        if item.is_dir() and item.name.startswith("assignment_"):
                            assignment_count += 1
                    
                    if assignment_count > 0:
                        # Get course name from Canvas or use ID
                        course_name = canvas_courses_map.get(course_id, f"Course {course_id}")
                        course_map[course_id] = {
                            "course_id": course_id,
                            "course_name": course_name,
                            "assignment_count": assignment_count
                        }
        
        # Convert map to list, avoiding duplicates
        courses = list(course_map.values())
        
        # Also check for legacy assignment folders (without course prefix)
        legacy_courses = []
        if base_download_dir.exists():
            for assignment_folder in base_download_dir.iterdir():
                if assignment_folder.is_dir() and assignment_folder.name.startswith("assignment_"):
                    assignment_id = assignment_folder.name.replace("assignment_", "")
                    # Add as "Unknown Course" if not already in a course folder
                    legacy_courses.append({
                        "course_id": "unknown",
                        "course_name": "Legacy Assignments",
                        "assignment_count": 1,
                        "legacy": True,
                        "assignment_id": assignment_id
                    })
        
        courses.extend(legacy_courses)
        return jsonify({"courses": courses})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/api/course-assignments-with-questions/<course_id>", methods=["GET"])
def api_get_course_assignments_with_questions(course_id):
    """Get assignments with parsed questions for a specific course, with names from Canvas."""
    try:
        cfg = load_env()
        base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
        assignments = []
        assignment_map = {}  # Store by assignment_id for deduplication
        
        # Try to fetch assignment names from Canvas
        canvas_assignments_map = {}
        try:
            api_url = cfg.get("CANVAS_API_URL", DEFAULTS["CANVAS_API_URL"])
            api_token = cfg.get("CANVAS_API_TOKEN", "")
            if api_url and api_token and course_id != "unknown":
                headers = {"Authorization": f"Bearer {api_token}"}
                resp = requests.get(f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments", 
                                   headers=headers, timeout=10, params={"per_page": 100})
                if resp.status_code == 200:
                    for assignment in resp.json():
                        assignment_id = str(assignment.get("id", ""))
                        # Use assignment name as the display name
                        assignment_name = assignment.get("name", f"Assignment {assignment_id}")
                        canvas_assignments_map[assignment_id] = assignment_name
        except Exception as canvas_err:
            print(f"Note: Could not fetch Canvas assignments: {canvas_err}")
        
        if course_id == "unknown":
            # Handle legacy assignment folders
            if base_download_dir.exists():
                for assignment_folder in base_download_dir.iterdir():
                    if assignment_folder.is_dir() and assignment_folder.name.startswith("assignment_"):
                        assignment_id = assignment_folder.name.replace("assignment_", "")
                        questions_dir = assignment_folder / "questions"
                        has_questions = questions_dir.exists() and any(f.suffix == '.md' for f in questions_dir.iterdir() if f.is_file())
                        
                        assignments.append({
                            "assignment_id": assignment_id,
                            "assignment_name": f"Assignment {assignment_id}",
                            "has_questions": has_questions,
                            "legacy": True
                        })
        else:
            # Handle course-specific folders
            course_dir = base_download_dir / f"course_{course_id}"
            if course_dir.exists():
                for assignment_folder in course_dir.iterdir():
                    if assignment_folder.is_dir() and assignment_folder.name.startswith("assignment_"):
                        assignment_id = assignment_folder.name.replace("assignment_", "")
                        questions_dir = assignment_folder / "questions"
                        has_questions = questions_dir.exists() and any(f.suffix == '.md' for f in questions_dir.iterdir() if f.is_file())
                        
                        # Get assignment name from Canvas or use ID
                        assignment_name = canvas_assignments_map.get(assignment_id, f"Assignment {assignment_id}")
                        assignment_map[assignment_id] = {
                            "assignment_id": assignment_id,
                            "assignment_name": assignment_name,
                            "has_questions": has_questions
                        }
                
                # Convert map to list, avoiding duplicates
                assignments = list(assignment_map.values())
        
        return jsonify({"assignments": assignments})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/api/parsed-questions/<course_id>/<assignment_id>", methods=["GET"])
def api_get_parsed_questions_with_course(course_id, assignment_id):
    """Get parsed questions content for an assignment (markdown format) with course context."""
    try:
        parsed_content = get_parsed_questions_content_with_course(course_id, assignment_id)
        if not parsed_content:
            return jsonify({"error": "No parsed questions found for this assignment"}), 404
        
        return jsonify({
            "success": True,
            "course_id": course_id,
            "assignment_id": assignment_id,
            "content": parsed_content,
            "format": "markdown"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/api/parsed-questions/<assignment_id>", methods=["GET"])
def api_get_parsed_questions(assignment_id):
    """Get parsed questions content for an assignment (markdown format) - legacy support."""
    try:
        parsed_content = get_parsed_questions_content(assignment_id)
        if not parsed_content:
            return jsonify({"error": "No parsed questions found for this assignment"}), 404
        
        return jsonify({
            "success": True,
            "assignment_id": assignment_id,
            "content": parsed_content,
            "format": "markdown"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/download/parsed-questions/<assignment_id>/<filename>")
def download_parsed_questions(assignment_id, filename):
    """Download a parsed questions file."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct path to parsed questions file
    assignment_dir = base_download_dir / f"assignment_{assignment_id}"
    questions_dir = assignment_dir / "questions"
    questions_file = questions_dir / filename
    
    if not questions_file.exists():
        flash("Parsed questions file not found", "danger")
        return redirect(url_for("upload_answer_key"))
    
    try:
        file_ext = ".md" if filename.endswith('.md') else ".txt"
        return send_from_directory(
            directory=str(questions_dir),
            path=filename,
            as_attachment=True,
            download_name=f"parsed_questions_assignment_{assignment_id}_{time.strftime('%Y%m%d_%H%M%S')}{file_ext}"
        )
    except Exception as e:
        flash(f"Error downloading parsed questions: {str(e)}", "danger")
        return redirect(url_for("upload_answer_key"))

@APP.route("/download/parsed-questions/<course_id>/<assignment_id>/<filename>")
def download_parsed_questions_with_course(course_id, assignment_id, filename):
    """Download a parsed questions file with course structure."""
    cfg = load_env()
    base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
    
    # Construct path to parsed questions file in course structure
    course_dir = base_download_dir / f"course_{course_id}"
    assignment_dir = course_dir / f"assignment_{assignment_id}"
    questions_dir = assignment_dir / "questions"
    questions_file = questions_dir / filename
    
    if not questions_file.exists():
        flash("Parsed questions file not found", "danger")
        return redirect(url_for("upload_answer_key"))
    
    try:
        file_ext = ".md" if filename.endswith('.md') else ".txt"
        return send_from_directory(
            directory=str(questions_dir),
            path=filename,
            as_attachment=True,
            download_name=f"parsed_questions_course_{course_id}_assignment_{assignment_id}_{time.strftime('%Y%m%d_%H%M%S')}{file_ext}"
        )
    except Exception as e:
        flash(f"Error downloading parsed questions: {str(e)}", "danger")
        return redirect(url_for("upload_answer_key"))

@APP.route("/api/answer-key-files")
def api_answer_key_files():
    """Get list of all uploaded answer key files."""
    cfg = load_env()
    data_dir = Path(cfg.get("DATA_DIR", DEFAULTS["DATA_DIR"]))
    
    # Exclude system files
    system_files = {'submissions_manifest.jsonl', 'results.jsonl', 'answer_key.json'}
    all_files = [f for f in data_dir.iterdir() if f.is_file() and f.name not in system_files and not f.name.startswith('.')]
    
    files_info = []
    for file_path in all_files:
        try:
            stat = file_path.stat()
            files_info.append({
                "filename": file_path.name,
                "size": stat.st_size,
                "modified": time.ctime(stat.st_mtime),
                "modified_timestamp": stat.st_mtime,
                "path": str(file_path)
            })
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
    
    # Sort by modification time (newest first)
    files_info.sort(key=lambda x: x["modified_timestamp"], reverse=True)
    
    return jsonify({
        "files": files_info,
        "current_answer_key": files_info[0] if files_info else None
    })

@APP.route("/api/compare-submissions", methods=["POST"])
def api_compare_submissions():
    """Compare student submissions to answer key using OpenRouter LLM for intelligent comparison."""
    data = request.get_json()
    assignment_id = data.get("assignment_id")
    course_id = data.get("course_id")
    max_workers = data.get("max_workers", 10)  # Increased default to 10 for better throughput
    
    if not assignment_id:
        return jsonify({"error": "assignment_id is required"}), 400
    
    try:
        cfg = load_env()
        data_dir = Path(cfg.get("DATA_DIR", DEFAULTS["DATA_DIR"]))
        base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
        
        # Get assignment points from Canvas API
        points_possible = 100  # Default fallback
        try:
            api_url = cfg.get("CANVAS_API_URL", DEFAULTS["CANVAS_API_URL"])
            api_token = cfg.get("CANVAS_API_TOKEN", "")
            if api_url and api_token and course_id and course_id != "unknown":
                headers = {"Authorization": f"Bearer {api_token}"}
                resp = requests.get(
                    f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}",
                    headers=headers,
                    timeout=10
                )
                if resp.status_code == 200:
                    points_possible = resp.json().get("points_possible", 100)
                    print(f"✅ Assignment {assignment_id} is worth {points_possible} points")
        except Exception as canvas_err:
            print(f"Note: Could not fetch assignment points from Canvas: {canvas_err}")
        
        # Determine the correct manifest path based on course_id
        if course_id and course_id != "unknown":
            manifest_path = data_dir / f"submissions_manifest_course_{course_id}_assignment_{assignment_id}.jsonl"
            # Also try the legacy manifest path
            if not manifest_path.exists():
                manifest_path = data_dir / f"submissions_manifest_assignment_{assignment_id}.jsonl"
            assignment_dir = base_download_dir / f"course_{course_id}" / f"assignment_{assignment_id}"
        else:
            manifest_path = data_dir / f"submissions_manifest_assignment_{assignment_id}.jsonl"
            assignment_dir = base_download_dir / f"assignment_{assignment_id}"
        
        # Get parsed questions or answer key
        parsed_questions_content = None
        if course_id and course_id != "unknown":
            parsed_questions_content = get_parsed_questions_content_with_course(course_id, assignment_id)
        
        if not parsed_questions_content:
            parsed_questions_content = get_parsed_questions_content(assignment_id)
        
        if parsed_questions_content:
            print(f"✅ Using parsed questions (markdown) for assignment {assignment_id}")
            answer_key_content = parsed_questions_content
        else:
            print(f"⚠️ No parsed questions found, using original answer key for assignment {assignment_id}")
            answer_key_content = get_answer_key_content(assignment_id)
            if not answer_key_content:
                return jsonify({"error": "No answer key or parsed questions found"}), 400
        
        if not answer_key_content:
            return jsonify({"error": "Could not load answer key or parsed questions"}), 400
        
        print(f"� Answer key/questions loaded ({len(answer_key_content)} characters)")
        
        # Load student submissions from manifest
        if not manifest_path.exists():
            return jsonify({"error": f"No submissions manifest found for assignment {assignment_id}"}), 404
        
        # Get OpenRouter credentials
        openrouter_api_key = cfg.get("OPENROUTER_API_KEY")
        openrouter_model = cfg.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
        
        if not openrouter_api_key:
            return jsonify({"error": "OpenRouter API key not configured"}), 400
        
        # Load all submissions first
        submissions_to_grade = []
        with open(manifest_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    submission = json.loads(line)
                    user_id = submission.get("user_id")
                    user_name = submission.get("user_name", f"User_{user_id}")
                    
                    # Get student's submission text
                    student_text = ""
                    if submission.get("has_body") and submission.get("body_text"):
                        student_text = submission.get("body_text", "")
                    else:
                        # Look for text in attachments
                        attachments = submission.get("attachments", [])
                        for attachment in attachments:
                            saved_path = attachment.get("saved_path")
                            if saved_path and Path(saved_path).exists():
                                try:
                                    with open(saved_path, 'r', encoding='utf-8') as af:
                                        student_text = af.read()
                                        break
                                except Exception:
                                    continue
                    
                    submissions_to_grade.append({
                        "user_id": user_id,
                        "user_name": user_name,
                        "student_text": student_text
                    })
                except Exception as e:
                    print(f"Error loading submission: {e}")
                    continue
        
        print(f"🔄 Starting parallel grading of {len(submissions_to_grade)} submissions with {max_workers} workers...")
        
        def grade_single_submission(submission_data):
            """Grade a single submission using OpenRouter API with rate limiting."""
            user_id = submission_data["user_id"]
            user_name = submission_data["user_name"]
            student_text = submission_data["student_text"]
            
            if not student_text:
                return {
                    "user_id": user_id,
                    "user_name": user_name,
                    "error": "No readable submission content found",
                    "score": 0,
                    "points": 0,
                    "feedback": "Could not read submission"
                }
            
            # Create comparison prompt for OpenRouter
            comparison_prompt = f"""You are an expert grader. Compare the student's submission to the answer key/expected answers and provide a score.

ANSWER KEY / EXPECTED ANSWERS:
{answer_key_content}

---

STUDENT'S SUBMISSION:
{student_text}

---

EVALUATION INSTRUCTIONS:
1. Carefully compare the student's submission to the expected answers
2. Evaluate if the student's answers are conceptually correct even if worded differently
3. Look for equivalent solutions and acceptable variations
4. Provide a score from 0-100 based on accuracy and completeness
5. Explain your reasoning and identify any errors or missing concepts

Please provide your response in this format:
SCORE: [0-100]
FEEDBACK: [Your detailed feedback explaining the score, what was correct, what was missing, and suggestions for improvement]
"""
            
            try:
                payload = {
                    "model": openrouter_model,
                    "messages": [{"role": "user", "content": comparison_prompt}]
                }
                
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 429:
                    # Rate limited - wait and retry
                    print(f"  ⏱️  Rate limited for {user_id}, retrying...")
                    time.sleep(2)
                    response = requests.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {openrouter_api_key}",
                            "Content-Type": "application/json"
                        },
                        json=payload,
                        timeout=120
                    )
                
                if response.status_code != 200:
                    print(f"  ❌ OpenRouter error for {user_id}: {response.status_code}")
                    return {
                        "user_id": user_id,
                        "user_name": user_name,
                        "error": f"OpenRouter API error: {response.text}",
                        "score": 0,
                        "points": 0,
                        "feedback": "Failed to grade submission"
                    }
                
                response_text = response.json()["choices"][0]["message"]["content"]
                
                # Extract score and feedback from response
                score_percentage = 0
                feedback = response_text
                
                # Try to extract score from response
                score_match = re.search(r'SCORE:\s*(\d+)', response_text, re.IGNORECASE)
                if score_match:
                    score_percentage = int(score_match.group(1))
                    # Clamp score between 0 and 100
                    score_percentage = max(0, min(100, score_percentage))
                
                # Extract feedback section
                feedback_match = re.search(r'FEEDBACK:\s*(.+?)(?:$)', response_text, re.IGNORECASE | re.DOTALL)
                if feedback_match:
                    feedback = feedback_match.group(1).strip()
                
                # Convert percentage to actual points based on assignment worth
                actual_points = (score_percentage / 100.0) * points_possible
                
                print(f"  ✅ {user_id}: {score_percentage}% = {actual_points:.2f}/{points_possible} points")
                
                return {
                    "user_id": user_id,
                    "user_name": user_name,
                    "score": score_percentage,
                    "points": round(actual_points, 2),
                    "points_possible": points_possible,
                    "feedback": feedback,
                    "full_response": response_text
                }
                
            except Exception as e:
                print(f"  ❌ Error grading {user_id}: {str(e)}")
                return {
                    "user_id": user_id,
                    "user_name": user_name,
                    "error": f"Grading error: {str(e)}",
                    "score": 0,
                    "points": 0,
                    "points_possible": points_possible,
                    "feedback": "Failed to grade submission"
                }
        
        # Use ThreadPoolExecutor for parallel processing with rate limiting
        comparison_results = []
        start_time = time.time()
        
        # Rate limiting: stagger submissions based on worker count
        # For 10 workers, add ~0.5s delay between submissions to avoid rate limits
        submission_delay = 0.5 if max_workers >= 10 else 0.2
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks with staggered timing to avoid rate limits
            future_to_submission = {}
            for i, sub in enumerate(submissions_to_grade):
                # Stagger submission of tasks
                delay = i * submission_delay
                time.sleep(min(delay, 0.1))  # Don't sleep more than 0.1s per submission
                future = executor.submit(grade_single_submission, sub)
                future_to_submission[future] = sub
            
            # Collect results as they complete
            for future in as_completed(future_to_submission):
                result = future.result()
                comparison_results.append(result)
        
        elapsed_time = time.time() - start_time
        
        # Save detailed results
        if course_id and course_id != "unknown":
            results_file = data_dir / f"comparison_results_course_{course_id}_assignment_{assignment_id}.jsonl"
        else:
            results_file = data_dir / f"comparison_results_assignment_{assignment_id}.jsonl"
        
        with open(results_file, 'w', encoding='utf-8') as f:
            for result in comparison_results:
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
        
        # Calculate summary statistics
        total_students = len(comparison_results)
        successful_grades = [r for r in comparison_results if "score" in r and "error" not in r]
        avg_percentage = sum(r.get("score", 0) for r in successful_grades) / len(successful_grades) if successful_grades else 0
        avg_points = sum(r.get("points", 0) for r in successful_grades) / len(successful_grades) if successful_grades else 0
        failed_count = total_students - len(successful_grades)
        
        summary = {
            "assignment_id": assignment_id,
            "course_id": course_id,
            "total_students": total_students,
            "successfully_graded": len(successful_grades),
            "failed_to_grade": failed_count,
            "average_percentage": round(avg_percentage, 2),
            "average_points": round(avg_points, 2),
            "points_possible": points_possible,
            "results_file": str(results_file),
            "processing_time_seconds": round(elapsed_time, 2),
            "workers_used": max_workers,
            "comparison_results": comparison_results
        }
        
        print(f"✅ Comparison complete: {total_students} students, {len(successful_grades)} graded, {avg_percentage:.1f}% avg ({avg_points:.2f}/{points_possible} pts)")
        
        return jsonify(summary)
        
    except Exception as e:
        print(f"❌ Comparison error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@APP.route("/api/compare-submissions-stream", methods=["POST"])
def api_compare_submissions_stream():
    """Stream comparison progress to client using Server-Sent Events."""
    data = request.get_json()
    assignment_id = data.get("assignment_id")
    course_id = data.get("course_id")
    max_workers = data.get("max_workers", 10)
    
    if not assignment_id:
        return jsonify({"error": "assignment_id is required"}), 400
    
    # Generate a unique session ID for this grading task
    import uuid
    session_id = str(uuid.uuid4())[:8]
    
    def generate_events():
        """Generator function for Server-Sent Events."""
        try:
            cfg = load_env()
            data_dir = Path(cfg.get("DATA_DIR", DEFAULTS["DATA_DIR"]))
            base_download_dir = Path(cfg.get("CANVAS_DOWNLOAD_DIR", "./data/downloads"))
            
            # Get assignment points from Canvas API
            points_possible = 100
            try:
                api_url = cfg.get("CANVAS_API_URL", DEFAULTS["CANVAS_API_URL"])
                api_token = cfg.get("CANVAS_API_TOKEN", "")
                if api_url and api_token and course_id and course_id != "unknown":
                    headers = {"Authorization": f"Bearer {api_token}"}
                    resp = requests.get(
                        f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}",
                        headers=headers,
                        timeout=10
                    )
                    if resp.status_code == 200:
                        points_possible = resp.json().get("points_possible", 100)
            except Exception as canvas_err:
                print(f"Note: Could not fetch assignment points: {canvas_err}")
            
            # Get parsed questions
            parsed_questions_content = None
            if course_id and course_id != "unknown":
                parsed_questions_content = get_parsed_questions_content_with_course(course_id, assignment_id)
            
            if not parsed_questions_content:
                parsed_questions_content = get_parsed_questions_content(assignment_id)
            
            if not parsed_questions_content:
                parsed_questions_content = get_answer_key_content(assignment_id)
            
            if not parsed_questions_content:
                yield f"data: {json.dumps({'error': 'No answer key or parsed questions found'})}\n\n"
                return
            
            # Determine manifest path
            if course_id and course_id != "unknown":
                manifest_path = data_dir / f"submissions_manifest_course_{course_id}_assignment_{assignment_id}.jsonl"
                if not manifest_path.exists():
                    manifest_path = data_dir / f"submissions_manifest_assignment_{assignment_id}.jsonl"
            else:
                manifest_path = data_dir / f"submissions_manifest_assignment_{assignment_id}.jsonl"
            
            if not manifest_path.exists():
                yield f"data: {json.dumps({'error': f'No submissions manifest found'})}\n\n"
                return
            
            # Load submissions
            submissions_to_grade = []
            with open(manifest_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        submission = json.loads(line)
                        user_id = submission.get("user_id")
                        user_name = submission.get("user_name", f"User_{user_id}")
                        
                        student_text = ""
                        if submission.get("has_body") and submission.get("body_text"):
                            student_text = submission.get("body_text", "")
                        else:
                            attachments = submission.get("attachments", [])
                            for attachment in attachments:
                                saved_path = attachment.get("saved_path")
                                if saved_path and Path(saved_path).exists():
                                    try:
                                        with open(saved_path, 'r', encoding='utf-8') as af:
                                            student_text = af.read()
                                            break
                                    except Exception:
                                        continue
                        
                        submissions_to_grade.append({
                            "user_id": user_id,
                            "user_name": user_name,
                            "student_text": student_text
                        })
                    except Exception:
                        continue
            
            total_students = len(submissions_to_grade)
            yield f"data: {json.dumps({'type': 'start', 'total': total_students, 'points_possible': points_possible})}\n\n"
            
            # Get OpenRouter credentials
            openrouter_api_key = cfg.get("OPENROUTER_API_KEY")
            openrouter_model = cfg.get("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free")
            
            if not openrouter_api_key:
                yield f"data: {json.dumps({'error': 'OpenRouter API key not configured'})}\n\n"
                return
            
            completed = 0
            results = []
            
            def grade_submission_wrapper(submission_data):
                """Wrapper to grade and yield progress."""
                nonlocal completed
                user_id = submission_data["user_id"]
                user_name = submission_data["user_name"]
                student_text = submission_data["student_text"]
                
                if not student_text:
                    result = {
                        "user_id": user_id,
                        "user_name": user_name,
                        "error": "No readable submission content",
                        "score": 0,
                        "points": 0
                    }
                else:
                    # Grade using OpenRouter
                    comparison_prompt = f"""You are an expert grader. Compare the student's submission to the answer key/expected answers and provide a score.

ANSWER KEY / EXPECTED ANSWERS:
{parsed_questions_content}

---

STUDENT'S SUBMISSION:
{student_text}

---

EVALUATION INSTRUCTIONS:
1. Carefully compare the student's submission to the expected answers
2. Evaluate if the student's answers are conceptually correct even if worded differently
3. Look for equivalent solutions and acceptable variations
4. Provide a score from 0-100 based on accuracy and completeness
5. Explain your reasoning and identify any errors or missing concepts

Please provide your response in this format:
SCORE: [0-100]
FEEDBACK: [Your detailed feedback explaining the score, what was correct, what was missing, and suggestions for improvement]
"""
                    
                    try:
                        payload = {
                            "model": openrouter_model,
                            "messages": [{"role": "user", "content": comparison_prompt}]
                        }
                        
                        response = requests.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {openrouter_api_key}",
                                "Content-Type": "application/json"
                            },
                            json=payload,
                            timeout=120
                        )
                        
                        if response.status_code == 429:
                            time.sleep(2)
                            response = requests.post(
                                "https://openrouter.ai/api/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {openrouter_api_key}",
                                    "Content-Type": "application/json"
                                },
                                json=payload,
                                timeout=120
                            )
                        
                        if response.status_code != 200:
                            result = {
                                "user_id": user_id,
                                "user_name": user_name,
                                "error": f"OpenRouter API error: {response.status_code}",
                                "score": 0,
                                "points": 0
                            }
                        else:
                            response_text = response.json()["choices"][0]["message"]["content"]
                            score_percentage = 0
                            feedback = response_text
                            
                            score_match = re.search(r'SCORE:\s*(\d+)', response_text, re.IGNORECASE)
                            if score_match:
                                score_percentage = int(score_match.group(1))
                                score_percentage = max(0, min(100, score_percentage))
                            
                            feedback_match = re.search(r'FEEDBACK:\s*(.+?)(?:$)', response_text, re.IGNORECASE | re.DOTALL)
                            if feedback_match:
                                feedback = feedback_match.group(1).strip()
                            
                            actual_points = (score_percentage / 100.0) * points_possible
                            
                            result = {
                                "user_id": user_id,
                                "user_name": user_name,
                                "score": score_percentage,
                                "points": round(actual_points, 2),
                                "points_possible": points_possible,
                                "feedback": feedback,
                                "full_response": response_text
                            }
                    except Exception as e:
                        result = {
                            "user_id": user_id,
                            "user_name": user_name,
                            "error": f"Grading error: {str(e)}",
                            "score": 0,
                            "points": 0
                        }
                
                return result
            
            # Grade with parallel processing and stream results
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for i, sub in enumerate(submissions_to_grade):
                    time.sleep(0.1)  # Small delay to stagger submissions
                    future = executor.submit(grade_submission_wrapper, sub)
                    futures.append((future, sub.get("user_id"), sub.get("user_name")))
                
                for future, user_id, user_name in futures:
                    result = future.result()
                    results.append(result)
                    completed += 1
                    
                    # Stream progress update
                    score = result.get("score", 0)
                    points = result.get("points", 0)
                    yield f"data: {json.dumps({'type': 'progress', 'completed': completed, 'total': total_students, 'current': f'{user_id} - {score}%', 'score': score, 'points': points})}\n\n"
            
            # Save results
            if course_id and course_id != "unknown":
                results_file = data_dir / f"comparison_results_course_{course_id}_assignment_{assignment_id}.jsonl"
            else:
                results_file = data_dir / f"comparison_results_assignment_{assignment_id}.jsonl"
            
            with open(results_file, 'w', encoding='utf-8') as f:
                for result in results:
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')
            
            # Calculate summary
            successful_grades = [r for r in results if "score" in r and "error" not in r]
            avg_percentage = sum(r.get("score", 0) for r in successful_grades) / len(successful_grades) if successful_grades else 0
            avg_points = sum(r.get("points", 0) for r in successful_grades) / len(successful_grades) if successful_grades else 0
            
            # Build complete event with proper JSON encoding
            complete_event = {
                'type': 'complete',
                'total': total_students,
                'successful': len(successful_grades),
                'average_percentage': round(avg_percentage, 2),
                'average_points': round(avg_points, 2),
                'points_possible': points_possible,
                'results': results
            }
            yield f"data: {json.dumps(complete_event, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(generate_events(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
    })

@APP.route("/api/comparison-results/<assignment_id>", methods=["GET"])
def api_get_comparison_results(assignment_id):
    """Get comparison results for a specific assignment."""
    try:
        cfg = load_env()
        data_dir = Path(cfg.get("DATA_DIR", DEFAULTS["DATA_DIR"]))
        results_file = data_dir / f"comparison_results_assignment_{assignment_id}.jsonl"
        
        if not results_file.exists():
            return jsonify({"error": f"No comparison results found for assignment {assignment_id}"}), 404
        
        results = []
        with open(results_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    results.append(json.loads(line))
                except Exception:
                    continue
        
        # Calculate summary statistics
        total_students = len(results)
        if total_students == 0:
            return jsonify({"error": "No results found"}), 404
        
        total_questions = results[0].get("total_questions", 0) if results else 0
        avg_score = sum(r.get("score_percentage", 0) for r in results) / total_students
        
        summary = {
            "assignment_id": assignment_id,
            "total_students": total_students,
            "total_questions": total_questions,
            "average_score": round(avg_score, 2),
            "results": results
        }
        
        return jsonify(summary)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/api/comparison-results/<course_id>/<assignment_id>", methods=["GET"])
def api_get_comparison_results_with_course(course_id, assignment_id):
    """Get comparison results for a specific course and assignment."""
    try:
        cfg = load_env()
        data_dir = Path(cfg.get("DATA_DIR", DEFAULTS["DATA_DIR"]))
        
        # Try course-specific file first
        results_file = data_dir / f"comparison_results_course_{course_id}_assignment_{assignment_id}.jsonl"
        
        # Fall back to legacy file if course-specific doesn't exist
        if not results_file.exists():
            results_file = data_dir / f"comparison_results_assignment_{assignment_id}.jsonl"
        
        if not results_file.exists():
            return jsonify({"error": f"No comparison results found for course {course_id}, assignment {assignment_id}"}), 404
        
        results = []
        with open(results_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    results.append(json.loads(line))
                except Exception:
                    continue
        
        # Calculate summary statistics
        total_students = len(results)
        if total_students == 0:
            return jsonify({"error": "No results found"}), 404
        
        # Get average score (handle both 'score' and 'score_percentage' fields)
        scores = []
        for r in results:
            score = r.get("score", r.get("score_percentage", 0))
            if score > 0 or "error" not in r:
                scores.append(score)
        
        avg_score = (sum(scores) / len(scores)) if scores else 0
        
        summary = {
            "course_id": course_id,
            "assignment_id": assignment_id,
            "total_students": total_students,
            "average_score": round(avg_score, 2),
            "results": results
        }
        
        return jsonify(summary)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@APP.route("/api/grade", methods=["POST"])
def api_grade():
    payload = request.get_json() or {}
    backend = payload.get("backend")
    prompt = payload.get("prompt")
    if not backend or not prompt:
        return jsonify({"error": "backend and prompt required"}), 400
    cfg = load_env()
    
    # Allow course_id and assignment_id to be passed in payload or use config defaults
    course_id = payload.get("course_id") or cfg.get("CANVAS_COURSE_ID")
    assignment_id = payload.get("assignment_id") or cfg.get("CANVAS_ASSIGNMENT_ID")
    
    if not course_id or not assignment_id:
        return jsonify({"error": "course_id and assignment_id are required"}), 400
    
    out_file = os.path.join(cfg.get("DATA_DIR", "./data"), cfg.get("RESULTS_FILE", "results.jsonl"))
    try:
        summary = grade_assignments(
            backend=backend,
            prompt=prompt,
            out_path=out_file,
            canvas_api_url=cfg.get("CANVAS_API_URL"),
            canvas_api_token=cfg.get("CANVAS_API_TOKEN"),
            course_id=course_id,
            assignment_id=assignment_id,
            openrouter_api_key=cfg.get("OPENROUTER_API_KEY"),
            openrouter_model=cfg.get("OPENROUTER_MODEL"),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "summary": summary})

# Minimal JSON APIs for stats (reads manifest/results)
@APP.route("/api/manifest", methods=["GET"])
def api_manifest():
    cfg = load_env()
    path = os.path.join(cfg.get("DATA_DIR", "./data"), cfg.get("MANIFEST_FILE", "submissions_manifest.jsonl"))
    rows = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return jsonify(rows)

@APP.route("/api/results", methods=["GET"])
def api_results():
    cfg = load_env()
    path = os.path.join(cfg.get("DATA_DIR", "./data"), cfg.get("RESULTS_FILE", "results.jsonl"))
    rows = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    return jsonify(rows)

# Simple pages (render templates; templates have JS that consumes above APIs)
@APP.route("/assignments")
def assignments():
    return render_template("assignment.html")

@APP.route("/students")
def students():
    return render_template("student.html")

@APP.route("/questions")
def questions():
    return render_template("question.html")

@APP.route("/performance")
def performance():
    return render_template("performance.html")

if __name__ == "__main__":
    APP.run(debug=True)
=======
import json
import os
import statistics
from typing import Any, Dict, List, Optional

import requests
import typer
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from grading import run_grading
from get_submissions import fetch_submissions
from utils_text import read_text_from_file, slice_answers_into_questions, heuristic_score, sanitize_filename


app = Flask(__name__)
cli = typer.Typer(help="Canvas Autograder Suite")


def load_env():
    load_dotenv(override=False)


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


def ensure_dirs():
    data_dir = env("DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    dl_dir = env("CANVAS_DOWNLOAD_DIR")
    if dl_dir:
        os.makedirs(dl_dir, exist_ok=True)


def _read_jsonl(path: str) -> List[dict]:
    items = []
    if not path or not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
    return items


def _read_json(path: str) -> Any:
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        try:
            return json.load(f)
        except Exception:
            return None


# In-memory caches
CACHE: Dict[str, Any] = {
    "manifest": [],
    "results": [],
    "answer_keys": {},
}


def assignment_root() -> Optional[str]:
    data_dir = env("DATA_DIR")
    if not data_dir:
        return None
    root = os.path.join(data_dir, "assignments")
    os.makedirs(root, exist_ok=True)
    return root


def assignment_folder(assignment_id: str | int) -> Optional[str]:
    root = assignment_root()
    if not root:
        return None
    folder = os.path.join(root, str(assignment_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def assignment_manifest_path(assignment_id: str | int) -> Optional[str]:
    folder = assignment_folder(assignment_id)
    if not folder:
        return None
    name = env("MANIFEST_FILE") or "submissions_manifest.jsonl"
    return os.path.join(folder, name)


def assignment_results_path(assignment_id: str | int) -> Optional[str]:
    folder = assignment_folder(assignment_id)
    if not folder:
        return None
    name = env("RESULTS_FILE") or "results.jsonl"
    return os.path.join(folder, name)


def assignment_answer_key_path(assignment_id: str | int) -> Optional[str]:
    folder = assignment_folder(assignment_id)
    if not folder or not os.path.isdir(folder):
        return None
    # First check answerkey subfolder
    answerkey_folder = os.path.join(folder, "answerkey")
    if os.path.isdir(answerkey_folder):
        for filename in os.listdir(answerkey_folder):
            if filename.lower().startswith("answer_key"):
                return os.path.join(answerkey_folder, filename)
    # Fallback to root folder for backwards compatibility
    for filename in os.listdir(folder):
        if filename.lower().startswith("answer_key") and not os.path.isdir(os.path.join(folder, filename)):
            return os.path.join(folder, filename)
    return None


def refresh_cache():
    data_dir = env("DATA_DIR")
    if not data_dir:
        return

    manifest_name = env("MANIFEST_FILE") or "submissions_manifest.jsonl"
    results_name = env("RESULTS_FILE") or "results.jsonl"

    manifests: List[dict] = []
    results: List[dict] = []
    answer_keys: Dict[str, Any] = {}

    base_manifest = os.path.join(data_dir, manifest_name)
    base_results = os.path.join(data_dir, results_name)
    manifests.extend(_read_jsonl(base_manifest))
    results.extend(_read_jsonl(base_results))

    root = assignment_root()
    if root and os.path.isdir(root):
        for assignment_id in os.listdir(root):
            folder = os.path.join(root, assignment_id)
            if not os.path.isdir(folder):
                continue
            manifests.extend(_read_jsonl(os.path.join(folder, manifest_name)))
            results.extend(_read_jsonl(os.path.join(folder, results_name)))
            ak_path = assignment_answer_key_path(assignment_id)
            if ak_path and ak_path.lower().endswith(".json"):
                answer_keys[str(assignment_id)] = _read_json(ak_path)

    legacy = env("ANSWER_KEY_FILE")
    if legacy:
        legacy_path = os.path.join(data_dir, legacy)
        if os.path.exists(legacy_path) and legacy_path.lower().endswith(".json"):
            answer_keys.setdefault("default", _read_json(legacy_path))

    CACHE["manifest"] = manifests
    CACHE["results"] = results
    CACHE["answer_keys"] = answer_keys


def is_config_complete() -> bool:
    required = [
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_COURSE_ID",
        "DATA_DIR",
        "MANIFEST_FILE",
        "RESULTS_FILE",
        "CANVAS_DOWNLOAD_DIR",
    ]
    return all(bool(env(k)) for k in required)


@app.before_request
def _maybe_redirect_setup():
    allowed = {
        "static",
        "setup",
        "api_canvas_validate",
        "api_canvas_courses",
        "api_canvas_assignments",
        "api_canvas_modules",
        "api_canvas_students",
        "api_canvas_submissions",
        "root",
        "dashboard",
        "assignments_page",
        "students_page",
        "questions_page",
        "performance_page",
        "upload_answer_key",
        "logo_png",
    }
    if request.endpoint in allowed:
        return
    if not is_config_complete():
        return redirect(url_for("setup"))


@app.route("/")
def root():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    refresh_cache()
    return render_template("index.html", env=os.environ)


@app.route("/setup", methods=["GET", "POST"])
def setup():
    load_env()
    ensure_dirs()
    msg = None
    if request.method == "POST":
        # Save .env
        form = request.form
        keys = [
            "CANVAS_API_URL",
            "CANVAS_API_TOKEN",
            "CANVAS_COURSE_ID",
            "CANVAS_ASSIGNMENT_ID",
            "DATA_DIR",
            "MANIFEST_FILE",
            "RESULTS_FILE",
            "CANVAS_DOWNLOAD_DIR",
            "OLLAMA_HOST",
            "OLLAMA_MODEL",
            "OPENROUTER_API_KEY",
            "OPENROUTER_MODEL",
        ]
        values = {k: form.get(k, "").strip() for k in keys}
        _write_env(values)
        load_env()
        refresh_cache()
        msg = "Settings saved."
    # Pre-fill form from env
    return render_template("setup.html", env=os.environ, message=msg)


def _write_env(kv: Dict[str, str]) -> None:
    # Merge with existing but overwrite keys present in kv
    path = os.path.join(os.getcwd(), ".env")
    existing: Dict[str, str] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                existing[k] = v
    existing.update({k: str(v) for k, v in kv.items() if v is not None})
    key_order = [
        "CANVAS_API_URL",
        "CANVAS_API_TOKEN",
        "CANVAS_COURSE_ID",
        "CANVAS_ASSIGNMENT_ID",
        "DATA_DIR",
        "MANIFEST_FILE",
        "RESULTS_FILE",
        "CANVAS_DOWNLOAD_DIR",
        "OLLAMA_HOST",
        "OLLAMA_MODEL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
    ]
    for k in existing.keys():
        if k not in key_order:
            key_order.append(k)
    lines = [f"{k}={existing.get(k, '')}" for k in key_order]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# Canvas passthrough APIs (usable by Setup Wizard before saving)
def _canvas_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _resolve_canvas_creds() -> tuple[str, str]:
    api_url = request.args.get("api_url") or env("CANVAS_API_URL")
    token = request.args.get("token") or env("CANVAS_API_TOKEN")
    return api_url, token


@app.get("/api/canvas/validate")
def api_canvas_validate():
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(f"{api_url.rstrip('/')}/api/v1/users/self", timeout=30)
        r.raise_for_status()
        return jsonify({"ok": True, "user": r.json()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.get("/api/canvas/courses")
def api_canvas_courses():
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(f"{api_url.rstrip('/')}/api/v1/courses", timeout=60)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/assignments")
def api_canvas_assignments(course_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments", timeout=60)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/modules")
def api_canvas_modules(course_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/modules", timeout=60)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/students")
def api_canvas_students(course_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(
            f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/users",
            params={"enrollment_type[]": "student"},
            timeout=60,
        )
        if r.status_code == 200:
            return jsonify(r.json())
    except Exception:
        pass
    # Fallback from manifest
    seen = {}
    for m in CACHE.get("manifest", []):
        if str(m.get("course_id")) == str(course_id):
            uid = m.get("user_id")
            if uid not in seen:
                seen[uid] = {"id": uid, "name": m.get("name")}
    return jsonify(list(seen.values()))


@app.get("/api/canvas/<course_id>/assignment/<assignment_id>/submissions")
def api_canvas_submissions(course_id, assignment_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        r = s.get(
            f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions",
            params={"include[]": ["attachments", "user"]},
            timeout=60,
        )
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/refresh")
def api_refresh():
    refresh_cache()
    return jsonify({"ok": True, "manifest": len(CACHE["manifest"]), "results": len(CACHE["results"])})


@app.post("/api/grade")
def api_grade():
    data = request.get_json(force=True) or {}
    backend = data.get("backend", "ollama")
    prompt = data.get("prompt", "Give concise feedback and a score /10.")
    assignment_id = data.get("assignment_id") or env("CANVAS_ASSIGNMENT_ID")
    if not assignment_id:
        return jsonify({"error": "assignment_id missing"}), 400
    data_dir = env("DATA_DIR") or "./data"
    results_name = env("RESULTS_FILE") or "results.jsonl"
    out_path = assignment_results_path(assignment_id) or os.path.join(data_dir, results_name)
    answer_key_path = assignment_answer_key_path(assignment_id)
    summary = run_grading(
        backend=backend,
        prompt=prompt,
        out_path=out_path,
        canvas_api_url=env("CANVAS_API_URL"),
        canvas_api_token=env("CANVAS_API_TOKEN"),
        course_id=env("CANVAS_COURSE_ID"),
        assignment_id=assignment_id,
        ollama_host=env("OLLAMA_HOST"),
        ollama_model=env("OLLAMA_MODEL"),
        openrouter_api_key=env("OPENROUTER_API_KEY"),
        openrouter_model=env("OPENROUTER_MODEL"),
        answer_key_path=answer_key_path,
    )
    refresh_cache()
    return jsonify(summary)


@app.post("/api/assignment/<assignment_id>/download")
def api_assignment_download(assignment_id):
    payload = request.get_json(silent=True) or {}
    course_id = payload.get("course_id") or env("CANVAS_COURSE_ID")
    if not course_id:
        return jsonify({"error": "course_id missing"}), 400
    api_url = env("CANVAS_API_URL")
    token = env("CANVAS_API_TOKEN")
    if not api_url or not token:
        return jsonify({"error": "Canvas API settings missing"}), 400
    data_dir = env("DATA_DIR") or "./data"
    downloads_root = env("CANVAS_DOWNLOAD_DIR") or os.path.join(data_dir, "downloads")
    manifest_name = env("MANIFEST_FILE") or "submissions_manifest.jsonl"
    manifest_path = assignment_manifest_path(assignment_id) or os.path.join(data_dir, manifest_name)
    try:
        summary = fetch_submissions(api_url, token, course_id, assignment_id, data_dir, downloads_root, manifest_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    refresh_cache()
    return jsonify(summary)


@app.post("/api/assignment/<assignment_id>/answer-key")
@app.post("/api/assignment/<assignment_id>/answer-key")
def api_assignment_answer_key_upload(assignment_id):
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "file missing"}), 400
    folder = assignment_folder(assignment_id)
    if not folder:
        return jsonify({"error": "data directory missing"}), 500
    
    # Create answerkey subfolder
    answerkey_folder = os.path.join(folder, "answerkey")
    os.makedirs(answerkey_folder, exist_ok=True)
    
    original = sanitize_filename(file.filename)
    ext = os.path.splitext(original)[1]
    target_name = f"answer_key{ext}" if ext else "answer_key"
    target_path = os.path.join(answerkey_folder, target_name)
    file.save(target_path)
    
    # If HTML file, extract and save body content as .txt
    if target_path.lower().endswith('.html'):
        try:
            with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            
            from html.parser import HTMLParser
            
            class BodyExtractor(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_body = False
                    self.body_content = []
                    self.skip_tags = {'script', 'style', 'meta', 'link', 'noscript'}
                    self.current_tag = None
                
                def handle_starttag(self, tag, attrs):
                    if tag.lower() == 'body':
                        self.in_body = True
                    elif self.in_body and tag.lower() not in self.skip_tags:
                        self.current_tag = tag.lower()
                
                def handle_endtag(self, tag):
                    if tag.lower() == 'body':
                        self.in_body = False
                    elif tag.lower() == self.current_tag:
                        self.current_tag = None
                
                def handle_data(self, data):
                    if self.in_body:
                        text = data.strip()
                        if text:
                            self.body_content.append(text)
                
                def get_body_text(self):
                    return '\n'.join(self.body_content)
            
            extractor = BodyExtractor()
            extractor.feed(html_content)
            body_text = extractor.get_body_text()
            
            # Save parsed body as .txt file
            parsed_path = os.path.join(answerkey_folder, "answer_key_parsed.txt")
            with open(parsed_path, 'w', encoding='utf-8') as f:
                f.write(body_text)
        except Exception as e:
            # If extraction fails, just continue without saving parsed version
            pass
    
    refresh_cache()
    return jsonify({"ok": True, "path": target_path})


@app.post("/api/assignment/<assignment_id>/parse-questions")
def api_parse_questions(assignment_id):
    folder = assignment_folder(assignment_id)
    if not folder:
        return jsonify({"error": "assignment folder not found"}), 400
    
    # Find answer key in answerkey subfolder
    answerkey_folder = os.path.join(folder, "answerkey")
    if not os.path.exists(answerkey_folder):
        return jsonify({"error": "no answer key uploaded yet. please upload an answer key first."}), 400
    
    files = os.listdir(answerkey_folder)
    if not files:
        return jsonify({"error": "no answer key file found in answerkey folder. please upload an answer key."}), 400
    
    answerkey_path = os.path.join(answerkey_folder, files[0])
    
    # Read answer key content
    try:
        # For HTML files, use the pre-parsed version if available
        if answerkey_path.lower().endswith('.html'):
            parsed_path = os.path.join(answerkey_folder, "answer_key_parsed.txt")
            if os.path.exists(parsed_path):
                with open(parsed_path, 'r', encoding='utf-8', errors='ignore') as f:
                    answerkey_content = f.read()
            else:
                # Fallback: parse on the fly
                with open(answerkey_path, 'r', encoding='utf-8', errors='ignore') as f:
                    answerkey_content = f.read()
        else:
            with open(answerkey_path, 'r', encoding='utf-8', errors='ignore') as f:
                answerkey_content = f.read()
    except Exception as e:
        return jsonify({"error": f"could not read answer key: {str(e)}"}), 400
    
    # Get OpenRouter API key
    openrouter_key = env('OPENROUTER_API_KEY')
    if not openrouter_key:
        return jsonify({"error": "OpenRouter API key not configured"}), 400
    
    try:
        r = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {openrouter_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://localhost:5000',
                'X-Title': 'Canvas Autograder'
            },
            json={
                'model': 'gpt-3.5-turbo',
                'messages': [
                    {
                        'role': 'system',
                        'content': 'You are a question parser. Extract all questions and their answers from the provided content. Return as markdown key-value pairs in the format: "## Question 1\n\n**Q:** [question text]\n\n**A:** [answer text]\n\n---\n\n" for each question. Be thorough and preserve all formatting.'
                    },
                    {
                        'role': 'user',
                        'content': f'Parse these questions and answers:\n\n{answerkey_content}'
                    }
                ]
            },
            timeout=60
        )
        
        if r.status_code != 200:
            return jsonify({"error": f"OpenRouter API error: {r.text}"}), 400
        
        result = r.json()
        parsed_content = result['choices'][0]['message']['content']
        
        # Create questions folder
        questions_folder = os.path.join(folder, "questions")
        os.makedirs(questions_folder, exist_ok=True)
        
        # Save parsed questions as markdown file
        output_path = os.path.join(questions_folder, "questions.md")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(parsed_content)
        
        return jsonify({"ok": True, "message": "questions parsed and saved", "output_file": output_path})
        
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"OpenRouter API request failed: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"error": f"error parsing questions: {str(e)}"}), 400


@app.get("/api/local/assignments")
def api_local_assignments():
    root = assignment_root()
    manifest_name = env("MANIFEST_FILE") or "submissions_manifest.jsonl"
    results_name = env("RESULTS_FILE") or "results.jsonl"
    data = []
    if root and os.path.isdir(root):
        for assignment_id in sorted(os.listdir(root)):
            folder = os.path.join(root, assignment_id)
            if not os.path.isdir(folder):
                continue
            data.append(
                {
                    "assignment_id": assignment_id,
                    "has_manifest": os.path.exists(os.path.join(folder, manifest_name)),
                    "has_results": os.path.exists(os.path.join(folder, results_name)),
                    "answer_key_path": assignment_answer_key_path(assignment_id),
                }
            )
    return jsonify(data)


# Stats helpers
def _results_by_assignment() -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for r in CACHE.get("results", []):
        aid = str(r.get("assignment_id"))
        out.setdefault(aid, []).append(r)
    return out


@app.get("/api/stats/assignments")
def api_stats_assignments():
    out = []
    for aid, lst in _results_by_assignment().items():
        scores = [x.get("score") for x in lst if isinstance(x.get("score"), (int, float))]
        avg = round(sum(scores) / len(scores), 2) if scores else None
        out.append({"assignment_id": aid, "count": len(lst), "avg": avg})
    return jsonify(out)


@app.get("/api/stats/students")
def api_stats_students():
    by_student: Dict[str, List[float]] = {}
    for r in CACHE.get("results", []):
        uid = str(r.get("user_id"))
        sc = r.get("score")
        if isinstance(sc, (int, float)):
            by_student.setdefault(uid, []).append(float(sc))
    out = []
    for uid, scores in by_student.items():
        out.append({"user_id": uid, "avg": round(sum(scores) / len(scores), 2), "count": len(scores)})
    return jsonify(out)


@app.get("/api/stats/questions")
def api_stats_questions():
    # Prefer structured per_question results from grading; fallback to heuristic
    qsum: Dict[str, List[float]] = {}
    used_structured = False
    for r in CACHE.get("results", []):
        pq = r.get("per_question")
        if isinstance(pq, list):
            used_structured = True
            for item in pq:
                try:
                    qid = str(item.get("qid"))
                    sc = item.get("score")
                    if sc is None and isinstance(item.get("correct"), bool):
                        sc = 10.0 if item["correct"] else 0.0
                    if isinstance(sc, (int, float)):
                        qsum.setdefault(qid, []).append(float(sc))
                except Exception:
                    continue
    if not used_structured:
        answer_keys = CACHE.get("answer_keys", {}) or {}
        for m in CACHE.get("manifest", []):
            assignment_id = str(m.get("assignment_id"))
            ak = answer_keys.get(assignment_id) or answer_keys.get("default")
            if not isinstance(ak, dict):
                continue
            qdefs = ak.get("questions", []) if isinstance(ak, dict) else []
            if not qdefs:
                continue
            text = m.get("body_text") or ""
            if not text:
                atts = m.get("attachments") or []
                if atts:
                    candidate = None
                    for a in atts:
                        p = a.get("saved_path")
                        if p and os.path.splitext(p)[1].lower() in (".txt", ".pdf", ".docx"):
                            candidate = p
                            break
                    if candidate:
                        t = read_text_from_file(candidate)
                        if t:
                            text = t
            parts = slice_answers_into_questions(text, ak)
            for q in qdefs:
                qid = str(q.get("id"))
                max_score = int(q.get("max_score", 10))
                kw = q.get("keywords", []) or []
                rub = q.get("rubric", "")
                sc = heuristic_score(parts.get(qid, ""), rub, kw, max_score)
                qsum.setdefault(qid, []).append(sc)
    out = []
    for qid, scores in qsum.items():
        if not scores:
            continue
        arr = [float(x) for x in scores]
        out.append({
            "qid": qid,
            "avg": round(sum(arr) / len(arr), 2),
            "median": round(statistics.median(arr), 2),
            "stdev": round(statistics.pstdev(arr), 2) if len(arr) > 1 else 0.0,
        })
    return jsonify(out)


@app.get("/api/assignment/<assignment_id>/submissions-count")
def api_assignment_submissions_count(assignment_id):
    manifest_path = assignment_manifest_path(assignment_id)
    if not manifest_path or not os.path.exists(manifest_path):
        return jsonify({"count": 0})
    
    count = 0
    try:
        with open(manifest_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line:
                    count += 1
    except Exception:
        pass
    
    return jsonify({"count": count})


@app.get("/api/assignment/<assignment_id>/scores")
def api_assignment_scores(assignment_id):
    lst = [r for r in CACHE.get("results", []) if str(r.get("assignment_id")) == str(assignment_id)]
    return jsonify(lst)


@app.get("/api/student/<user_id>/scores")
def api_student_scores(user_id):
    lst = [r for r in CACHE.get("results", []) if str(r.get("user_id")) == str(user_id)]
    return jsonify(lst)


@app.route("/upload/answer-key", methods=["GET", "POST"])
def upload_answer_key():
    msg = None
    if request.method == "POST":
        f = request.files.get("file")
        assignment_id = request.form.get("assignment_id") or request.args.get("assignment_id")
        if f and f.filename:
            if assignment_id:
                folder = assignment_folder(assignment_id)
                if not folder:
                    msg = "Data directory missing."
                else:
                    original = sanitize_filename(f.filename)
                    ext = os.path.splitext(original)[1]
                    save_name = f"answer_key{ext}" if ext else "answer_key"
                    save_path = os.path.join(folder, save_name)
                    f.save(save_path)
                    refresh_cache()
                    msg = f"Answer key for assignment {assignment_id} uploaded."
            else:
                data_dir = env("DATA_DIR") or "./data"
                os.makedirs(data_dir, exist_ok=True)
                save_name = sanitize_filename(f.filename)
                save_path = os.path.join(data_dir, save_name)
                f.save(save_path)
                _write_env({"ANSWER_KEY_FILE": save_name})
                load_env()
                refresh_cache()
                msg = f"Answer key uploaded as {save_name}."
    return render_template("upload_answer_key.html" if os.path.exists(os.path.join("templates", "upload_answer_key.html")) else "index.html", message=msg)


# Serve project-root logo file for use in templates/favicon
@app.get("/logo.png")
def logo_png():
    return send_from_directory(os.getcwd(), "AutoGrader-logo.png")


# Simple pages
@app.route("/assignments")
def assignments_page():
    refresh_cache()
    return render_template("assignment.html", env=os.environ)


@app.route("/students")
def students_page():
    refresh_cache()
    return render_template("student.html", env=os.environ)


@app.route("/questions")
def questions_page():
    refresh_cache()
    return render_template("question.html", env=os.environ)


@app.route("/performance")
def performance_page():
    refresh_cache()
    return render_template("performance.html", env=os.environ)


# Typer CLI
@cli.command()
def grade(
    backend: str = typer.Option("ollama", help="ollama|openrouter"),
    prompt: str = typer.Option("Give concise feedback and a score /10.", help="Prompt for the model"),
    prompt_file: Optional[str] = typer.Option(None, help="Path to prompt file"),
    out: Optional[str] = typer.Option(None, help="Output JSONL path"),
    assignment: Optional[str] = typer.Option(None, help="Assignment ID (overrides .env)"),
):
    load_env()
    ensure_dirs()
    refresh_cache()
    if prompt_file and os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    assignment_id = assignment or env("CANVAS_ASSIGNMENT_ID")
    if not assignment_id:
        typer.echo("Assignment ID required (use --assignment or set CANVAS_ASSIGNMENT_ID)", err=True)
        raise typer.Exit(code=1)
    data_dir = env("DATA_DIR") or "./data"
    results_name = env("RESULTS_FILE") or "results.jsonl"
    out_path = out or assignment_results_path(assignment_id) or os.path.join(data_dir, results_name)
    answer_key_path = assignment_answer_key_path(assignment_id)
    summary = run_grading(
        backend=backend,
        prompt=prompt,
        out_path=out_path,
        canvas_api_url=env("CANVAS_API_URL"),
        canvas_api_token=env("CANVAS_API_TOKEN"),
        course_id=env("CANVAS_COURSE_ID"),
        assignment_id=assignment_id,
        ollama_host=env("OLLAMA_HOST"),
        ollama_model=env("OLLAMA_MODEL"),
        openrouter_api_key=env("OPENROUTER_API_KEY"),
        openrouter_model=env("OPENROUTER_MODEL"),
        answer_key_path=answer_key_path,
    )
    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    load_env()
    ensure_dirs()
    refresh_cache()
    cli()
>>>>>>> origin/Chase
