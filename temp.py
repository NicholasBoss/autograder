from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
import requests

load_dotenv()
app = Flask(__name__)

# --- CONFIG ---
CANVAS_API_URL = os.getenv("CANVAS_API_URL")
CANVAS_API_TOKEN = os.getenv("CANVAS_API_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def canvas_headers():
    return {"Authorization": f"Bearer {CANVAS_API_TOKEN}"}

def openrouter_headers():
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

# --- ROUTES ---

@app.route("/")
def index():
    return render_template("submissions.html")


@app.route("/fetch_submissions", methods=["POST"])
def fetch_submissions():
    """Fetch submissions for a given course and assignment"""
    data = request.get_json()
    course_id = data.get("course_id")
    assignment_id = data.get("assignment_id")

    url = f"{CANVAS_API_URL}/courses/{course_id}/assignments/{assignment_id}/submissions?include[]=submission_comments&include[]=attachments"
    response = requests.get(url, headers=canvas_headers())

    if response.status_code != 200:
        return jsonify({"error": response.text}), response.status_code

    submissions = []
    for sub in response.json():
        attachments = sub.get("attachments", [])
        file_names = [a["filename"] for a in attachments]
        submissions.append({
            "user_id": sub.get("user_id"),
            "file_names": file_names,
            "body": sub.get("body", "") or "(No text body)"
        })

    return jsonify(submissions)


@app.route("/get_feedback", methods=["POST"])
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
        headers=openrouter_headers(),
        json=payload
    )

    if response.status_code != 200:
        return jsonify({"error": response.text}), response.status_code

    feedback = response.json()["choices"][0]["message"]["content"]
    return jsonify({"feedback": feedback})


if __name__ == "__main__":
    app.run(debug=True)
