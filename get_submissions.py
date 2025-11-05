<<<<<<< HEAD
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
=======
import json
import os
import sys
from typing import Dict, Iterable, List, Tuple

import requests
from dotenv import load_dotenv

from utils_text import sanitize_filename


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def ensure_dirs(data_dir: str, download_dir: str) -> Tuple[str, str]:
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(download_dir, exist_ok=True)
    return data_dir, download_dir


def session_with_token(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def paginate(s: requests.Session, url: str, params: Dict | None = None) -> Iterable[List[Dict]]:
    p = dict(params or {})
    while url:
        r = s.get(url, params=p, timeout=60)
        r.raise_for_status()
        yield r.json()
        link = r.headers.get("Link", "")
        next_url = None
        if link:
            parts = [x.strip() for x in link.split(",")]
            for part in parts:
                if 'rel="next"' in part:
                    seg = part.split(";")[0].strip()
                    if seg.startswith("<") and seg.endswith(">"):
                        next_url = seg[1:-1]
                        break
        url = next_url
        p = {}


def download_attachment(s: requests.Session, url: str, save_path: str) -> Tuple[bool, int]:
    try:
        r = s.get(url, timeout=120)
        r.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(r.content)
        
        # If HTML file, also save extracted body text as .txt
        if save_path.lower().endswith('.html'):
            try:
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
                html_content = r.content.decode('utf-8', errors='ignore')
                extractor.feed(html_content)
                body_text = extractor.get_body_text()
                
                # Save parsed body as .txt file
                parsed_path = save_path.replace('.html', '_parsed.txt')
                with open(parsed_path, 'w', encoding='utf-8') as f:
                    f.write(body_text)
            except Exception:
                # If extraction fails, just continue without saving parsed version
                pass
        
        return True, len(r.content)
    except Exception:
        return False, 0


def fetch_submissions(
    api_url: str,
    token: str,
    course_id: str,
    assignment_id: str,
    data_dir: str,
    downloads_root: str,
    manifest_path: str,
) -> dict:
    data_dir, downloads_root = ensure_dirs(data_dir, downloads_root)
    assignment_download_dir = os.path.join(downloads_root, f"assignment_{assignment_id}")
    os.makedirs(assignment_download_dir, exist_ok=True)

    s = session_with_token(token)
    sub_url = f"{api_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions"
    params = {"include[]": ["attachments", "user"]}

    total_students = 0
    files_downloaded = 0
    os.makedirs(os.path.dirname(manifest_path) or data_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as mf:
        for page in paginate(s, sub_url, params=params):
            for sub in page:
                total_students += 1
                user = sub.get("user") or {}
                user_name = user.get("name") or user.get("short_name") or f"user_{user.get('id')}"
                attachments_out = []
                atts = sub.get("attachments") or []
                for a in atts:
                    cfid = a.get("id")
                    orig = a.get("filename") or a.get("display_name") or f"file_{cfid}"
                    safe = sanitize_filename(orig)
                    base = f"user_{user.get('id')}_{sanitize_filename(user_name)}_{cfid}_{safe}"
                    save_path = os.path.join(assignment_download_dir, base)
                    ok, size = download_attachment(s, a.get("url"), save_path)
                    if ok:
                        files_downloaded += 1
                    attachments_out.append(
                        {
                            "canvas_file_id": cfid,
                            "original_filename": orig,
                            "saved_path": os.path.relpath(save_path).replace("\\", "/"),
                            "content_type": a.get("content-type"),
                            "size": size or a.get("size"),
                        }
                    )
                body = sub.get("body") or ""
                rec = {
                    "course_id": course_id,
                    "assignment_id": assignment_id,
                    "user_id": user.get("id"),
                    "name": user_name,
                    "attempt": sub.get("attempt"),
                    "workflow_state": sub.get("workflow_state"),
                    "submitted_at": sub.get("submitted_at"),
                    "has_body": bool(body.strip()),
                    "body_text": body,
                    "attachments": attachments_out,
                }
                mf.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return {
        "students": total_students,
        "files_downloaded": files_downloaded,
        "manifest_path": manifest_path,
        "download_dir": assignment_download_dir,
    }


def main():
    load_dotenv(override=False)
    api_url = env("CANVAS_API_URL", "https://canvas.instructure.com")
    token = env("CANVAS_API_TOKEN")
    course_id = env("CANVAS_COURSE_ID")
    assignment_id = env("CANVAS_ASSIGNMENT_ID")

    if not token or not course_id or not assignment_id:
        print("Missing CANVAS_API_TOKEN, CANVAS_COURSE_ID, or CANVAS_ASSIGNMENT_ID in .env", file=sys.stderr)
        sys.exit(1)

    data_dir = env("DATA_DIR", "./data") or "./data"
    downloads_root = env("CANVAS_DOWNLOAD_DIR", os.path.join(data_dir, "downloads")) or os.path.join(data_dir, "downloads")
    manifest_name = env("MANIFEST_FILE", "submissions_manifest.jsonl")
    assignment_dir = os.path.join(data_dir, "assignments", str(assignment_id))
    os.makedirs(assignment_dir, exist_ok=True)
    manifest_path = os.path.join(assignment_dir, manifest_name)

    summary = fetch_submissions(api_url, token, course_id, assignment_id, data_dir, downloads_root, manifest_path)

    print(
        f"Students: {summary['students']}  Files downloaded: {summary['files_downloaded']}  Manifest: {summary['manifest_path']}"
    )


if __name__ == "__main__":
    main()
>>>>>>> origin/Chase
