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
