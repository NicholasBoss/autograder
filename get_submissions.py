# get_submissions.py
import os
import requests
import json
import time
from urllib.parse import urljoin
from dotenv import load_dotenv
from utils_text import sanitize_filename

load_dotenv()
CANVAS_API_URL = os.getenv("CANVAS_API_URL", "https://canvas.instructure.com")
CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN", "")
CANVAS_COURSE_ID = os.getenv("CANVAS_COURSE_ID", "")
CANVAS_ASSIGNMENT_ID = os.getenv("CANVAS_ASSIGNMENT_ID", "")
DATA_DIR = os.getenv("DATA_DIR", "./data")
MANIFEST_FILE = os.getenv("MANIFEST_FILE", "submissions_manifest.jsonl")
DOWNLOAD_DIR = os.getenv("CANVAS_DOWNLOAD_DIR", "./data/downloads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

HEADERS = {
    "Authorization": f"Bearer {CANVAS_API_TOKEN}",
    "Accept": "application/json"
}

def _get_paginated(url, params=None):
    params = params or {}
    items = []
    next_url = url
    while next_url:
        r = requests.get(next_url, headers=HEADERS, params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Canvas API error: {r.status_code} - {r.text}")
        page_items = r.json()
        if isinstance(page_items, list):
            items.extend(page_items)
        else:
            # if Canvas returns object with 'users' etc
            items.extend(page_items.get('submissions', []))
        # Link header handling
        link = r.headers.get('Link', '')
        next_url = None
        if link:
            # Example Link: <https://...&page=2>; rel="next", <...>; rel="last"
            parts = link.split(',')
            for p in parts:
                if 'rel="next"' in p:
                    url_part = p.split(';')[0].strip().strip('<>').strip()
                    next_url = url_part
    return items

def download_file(url, save_path):
    try:
        r = requests.get(url, stream=True, headers=HEADERS, timeout=60)
        if r.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True, None
        else:
            return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def fetch_submissions():
    if not CANVAS_API_TOKEN:
        raise RuntimeError("CANVAS_API_TOKEN is not set in environment.")
    base = CANVAS_API_URL.rstrip('/') + '/'
    submissions_url = urljoin(base, f"api/v1/courses/{CANVAS_COURSE_ID}/assignments/{CANVAS_ASSIGNMENT_ID}/submissions")
    params = {
        "include[]": ["attachments", "user"],
        "per_page": 100
    }
    print("Fetching submissions (may take a while)...")
    items = _get_paginated(submissions_url, params=params)
    manifest_path = os.path.join(DATA_DIR, MANIFEST_FILE)
    downloaded = 0
    rows = []
    for s in items:
        user = s.get('user') or {}
        user_id = user.get('id') or s.get('user_id')
        name = user.get('name') or s.get('display_name') or f"user_{user_id}"
        attempt = s.get('attempt') or 1
        workflow_state = s.get('workflow_state')
        submitted_at = s.get('submitted_at')
        has_body = bool(s.get('body'))
        body_text = s.get('body') or ""
        attachments_list = []
        attachments = s.get('attachments') or []
        for a in attachments:
            canvas_file_id = a.get('id')
            original = a.get('filename') or a.get('display_name')
            download_url = a.get('url') or a.get('download_url')
            content_type = a.get('content-type') or a.get('content_type') or a.get('content-type')
            size = a.get('size')
            safe_name = sanitize_filename(f"user_{user_id}_{name}_{canvas_file_id}_{original}")
            saved_path = os.path.join(DOWNLOAD_DIR, safe_name)
            ok = False
            err = None
            if download_url:
                ok, err = download_file(download_url, saved_path)
            if ok:
                downloaded += 1
            attachments_list.append({
                "canvas_file_id": canvas_file_id,
                "original_filename": original,
                "saved_path": saved_path if ok else None,
                "content_type": content_type,
                "size": size,
                "download_error": err
            })
            # small pause to be polite
            time.sleep(0.1)
        row = {
            "course_id": CANVAS_COURSE_ID,
            "assignment_id": CANVAS_ASSIGNMENT_ID,
            "user_id": user_id,
            "name": name,
            "attempt": attempt,
            "workflow_state": workflow_state,
            "submitted_at": submitted_at,
            "has_body": has_body,
            "body_text": body_text,
            "attachments": attachments_list
        }
        rows.append(row)
    # write manifest
    with open(manifest_path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Done. Students: {len(rows)}; Files downloaded: {downloaded}; Manifest: {manifest_path}")
    return {"students": len(rows), "downloaded": downloaded, "manifest": manifest_path}

if __name__ == "__main__":
    try:
        summary = fetch_submissions()
        print(summary)
    except Exception as e:
        print("Error:", e)
