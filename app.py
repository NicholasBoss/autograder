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
        "api_canvas_module_items",
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
        # Fetch all assignments with pagination
        all_assignments = []
        page = 1
        while True:
            r = s.get(
                f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments",
                params={"per_page": 100, "page": page},
                timeout=60
            )
            r.raise_for_status()
            assignments = r.json()
            if not assignments:
                break
            all_assignments.extend(assignments)
            # Check if there are more pages
            if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                break
            page += 1
        return jsonify(all_assignments)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/modules")
def api_canvas_modules(course_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        # Fetch all modules with pagination
        all_modules = []
        page = 1
        while True:
            r = s.get(
                f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/modules",
                params={"per_page": 100, "page": page},
                timeout=60
            )
            r.raise_for_status()
            modules = r.json()
            if not modules:
                break
            all_modules.extend(modules)
            # Check if there are more pages
            if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                break
            page += 1
        return jsonify(all_modules)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/modules/<module_id>/items")
def api_canvas_module_items(course_id, module_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        # Fetch all module items with pagination
        all_items = []
        page = 1
        while True:
            r = s.get(
                f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/modules/{module_id}/items",
                params={"per_page": 100, "page": page},
                timeout=60
            )
            r.raise_for_status()
            items = r.json()
            if not items:
                break
            all_items.extend(items)
            # Check if there are more pages
            if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                break
            page += 1
        return jsonify(all_items)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/canvas/<course_id>/students")
def api_canvas_students(course_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        # Fetch all students with pagination
        all_students = []
        page = 1
        while True:
            r = s.get(
                f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/users",
                params={"enrollment_type[]": "student", "per_page": 100, "page": page},
                timeout=60,
            )
            if r.status_code != 200:
                break
            students = r.json()
            if not students:
                break
            all_students.extend(students)
            # Check if there are more pages
            if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                break
            page += 1
        if all_students:
            return jsonify(all_students)
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
    qinfo: Dict[str, Dict[str, str]] = {}  # Track assignment_id for each question
    used_structured = False
    for r in CACHE.get("results", []):
        pq = r.get("per_question")
        assignment_id = str(r.get("assignment_id"))
        if isinstance(pq, list):
            used_structured = True
            for item in pq:
                try:
                    qid = str(item.get("qid"))
                    # Create unique key combining assignment_id and qid
                    unique_key = f"{assignment_id}_{qid}"
                    sc = item.get("score")
                    if sc is None and isinstance(item.get("correct"), bool):
                        sc = 10.0 if item["correct"] else 0.0
                    if isinstance(sc, (int, float)):
                        qsum.setdefault(unique_key, []).append(float(sc))
                        if unique_key not in qinfo:
                            qinfo[unique_key] = {"assignment_id": assignment_id, "qid": qid}
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
                # Create unique key combining assignment_id and qid
                unique_key = f"{assignment_id}_{qid}"
                max_score = int(q.get("max_score", 10))
                kw = q.get("keywords", []) or []
                rub = q.get("rubric", "")
                sc = heuristic_score(parts.get(qid, ""), rub, kw, max_score)
                qsum.setdefault(unique_key, []).append(sc)
                if unique_key not in qinfo:
                    qinfo[unique_key] = {"assignment_id": assignment_id, "qid": qid}
    out = []
    for unique_key, scores in qsum.items():
        if not scores:
            continue
        arr = [float(x) for x in scores]
        out.append({
            "qid": qinfo.get(unique_key, {}).get("qid", unique_key),
            "assignment_id": qinfo.get(unique_key, {}).get("assignment_id", ""),
            "avg": round(sum(arr) / len(arr), 2),
            "median": round(statistics.median(arr), 2),
            "stdev": round(statistics.pstdev(arr), 2) if len(arr) > 1 else 0.0,
        })
    # Sort by assignment_id, then by qid
    out.sort(key=lambda x: (x.get("assignment_id", ""), x.get("qid", "")))
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


@app.get("/api/canvas/<course_id>/assignments/<assignment_id>/grades")
def api_canvas_assignment_grades(course_id, assignment_id):
    api_url, token = _resolve_canvas_creds()
    try:
        s = _canvas_session(token)
        # Fetch all submissions for the assignment with pagination
        all_submissions = []
        page = 1
        while True:
            r = s.get(
                f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions",
                params={"per_page": 100, "page": page, "include[]": ["user"]},
                timeout=60
            )
            r.raise_for_status()
            submissions = r.json()
            if not submissions:
                break
            all_submissions.extend(submissions)
            # Check if there are more pages
            if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                break
            page += 1
        
        # Format the submissions for display
        grades = []
        for sub in all_submissions:
            user = sub.get('user') or {}
            grades.append({
                "user_id": user.get('id') or sub.get('user_id'),
                "name": user.get('name') or sub.get('display_name') or f"user_{sub.get('user_id')}",
                "email": user.get('email'),
                "score": sub.get('score'),
                "grade": sub.get('grade'),
                "submitted_at": sub.get('submitted_at'),
                "workflow_state": sub.get('workflow_state'),
                "late": sub.get('late'),
                "missing": sub.get('missing'),
                "excused": sub.get('excused'),
            })
        
        return jsonify({"grades": grades, "count": len(grades)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/assignment/<assignment_id>/grade-comparison")
def api_grade_comparison(assignment_id):
    """Compare LLM grades vs Canvas grades for an assignment"""
    try:
        # Get LLM grades from local results
        results_path = assignment_results_path(assignment_id)
        llm_grades = {}
        if results_path and os.path.exists(results_path):
            for line in _read_jsonl(results_path):
                user_id = str(line.get("user_id"))
                llm_grades[user_id] = {
                    "name": line.get("name"),
                    "llm_score": line.get("score"),
                    "llm_reply": line.get("reply", "")[:500],  # Truncate reply
                    "per_question": line.get("per_question"),
                    "error": line.get("error"),
                }
        
        # Get Canvas grades
        course_id = env("CANVAS_COURSE_ID")
        api_url = env("CANVAS_API_URL")
        token = env("CANVAS_API_TOKEN")
        
        canvas_grades = {}
        if api_url and token and course_id:
            try:
                s = requests.Session()
                s.headers.update({"Authorization": f"Bearer {token}"})
                
                # Fetch all submissions with pagination
                all_submissions = []
                page = 1
                while True:
                    r = s.get(
                        f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions",
                        params={"per_page": 100, "page": page, "include[]": ["user"]},
                        timeout=60
                    )
                    if r.status_code != 200:
                        break
                    submissions = r.json()
                    if not submissions:
                        break
                    all_submissions.extend(submissions)
                    if 'link' not in r.headers or 'rel="next"' not in r.headers.get('link', ''):
                        break
                    page += 1
                
                for sub in all_submissions:
                    user_id = str(sub.get("user_id") or (sub.get("user") or {}).get("id"))
                    user = sub.get("user") or {}
                    canvas_grades[user_id] = {
                        "name": user.get("name") or sub.get("display_name"),
                        "canvas_score": sub.get("score"),
                        "canvas_grade": sub.get("grade"),
                        "submitted_at": sub.get("submitted_at"),
                        "workflow_state": sub.get("workflow_state"),
                    }
            except Exception as e:
                print(f"[DEBUG] Error fetching Canvas grades: {str(e)}")
        
        # Merge and compare
        all_user_ids = set(llm_grades.keys()) | set(canvas_grades.keys())
        comparisons = []
        
        for user_id in sorted(all_user_ids):
            llm_data = llm_grades.get(user_id, {})
            canvas_data = canvas_grades.get(user_id, {})
            
            llm_score = llm_data.get("llm_score")
            canvas_score = canvas_data.get("canvas_score")
            
            # Calculate difference
            difference = None
            if llm_score is not None and canvas_score is not None:
                difference = canvas_score - llm_score
            
            comparisons.append({
                "user_id": user_id,
                "name": llm_data.get("name") or canvas_data.get("name"),
                "llm_score": llm_score,
                "canvas_score": canvas_score,
                "difference": difference,
                "llm_error": llm_data.get("error"),
                "canvas_grade": canvas_data.get("canvas_grade"),
                "submitted_at": canvas_data.get("submitted_at"),
                "workflow_state": canvas_data.get("workflow_state"),
                "per_question": llm_data.get("per_question"),
            })
        
        return jsonify({"comparisons": comparisons, "count": len(comparisons)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/grade-comparison")
def grade_comparison_page():
    refresh_cache()
    return render_template("grade_comparison.html", env=os.environ)


@app.route("/grades")
def grades_page():
    refresh_cache()
    return render_template("grades.html", env=os.environ)


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
