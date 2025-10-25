## ✨ AutoMark: AI-Powered Grading for Canvas

AutoMark is a local application designed to streamline the grading process for educators using **Canvas LMS**. It automates the downloading of student submissions, uses AI for grading, and presents the results in an easy-to-use web dashboard.

-----

### ✅ Key Features

| Feature | Description |
| :--- | :--- |
| **Fetches Submissions** | Downloads student work directly from Canvas. 📥 |
| **AI Grading** | Grades submissions using **OpenRouter** (cloud AI). ☁️ |
| **Web Dashboard** | Displays analytics and results using a **Flask web app**. 📊 |
| **Answer Key** | Allows you to upload an answer key for simple scoring options. ✅ |
| **Setup Wizard** | Guides you through entering your Canvas and AI model settings to create a `.env` file automatically. 🧭 |

-----

### 📦 Installation & Setup

To get started, you'll first need to install the required Python packages:

```bash
pip install -r requirements.txt
```

#### ▶️ Running AutoMark

1.  Start the Flask web application:

    ```bash
    export FLASK_APP=app.py
    flask run
    ```

2.  Open the setup wizard in your web browser:

    👉 **[http://127.0.0.1:5000/setup](http://127.0.0.1:5000/setup)**

3.  Follow the setup steps:

      * Enter your **Canvas API Token**.
      * Pick your **Course** and **Assignment**.
      * Select your grading backend (OpenRouter is supported).
      * Click **Save**.

-----

### 📊 Viewing Results

The web dashboard provides different views for analyzing results:

  * **Assignments:** Overall averages and completion rates.
  * **Students:** Individual progress and scores.
  * **Questions:** Skill breakdowns and performance per question.
  * **Performance:** Grading trends over time.

You can click on items within the dashboard to drill down and see individual student responses and AI feedback.

-----

### ❤️ Built for Teachers

AutoMark is a tool built to **help teachers save hours** and provide more detailed feedback. If you have ideas, feedback, or need help extending the tool, feel free to reach out\!
