# Quick Reference: Answer Key-Based Grading

## ⚡ Quick Start

### 1. Upload Answer Key
```
Dashboard → Upload Answer Key
→ Select Course & Assignment
→ Upload answer key file
→ Click "Parse Questions"
```

### 2. Grade Submissions
```
Dashboard → Assignments
→ Select Course & Assignment
→ Click "Start Grading"
(Parsed questions are used automatically)
```

### 3. Review Results
```
Dashboard → Performance
→ View student scores
→ See LLM feedback
```

## 🔄 How It Works

```
Answer Key (SQL, JSON, etc.)
         ↓
    [OpenRouter AI]
         ↓
Parsed Questions (Markdown)
         ↓
Student Submission + Parsed Questions
         ↓
    [OpenRouter AI - Compare & Score]
         ↓
Score (0-100) + Feedback
```

## 📁 File Structure

```
data/downloads/
└── course_268730/
    └── assignment_12039643/
        ├── answer_key/               ← Upload here
        │   └── my_answer_key.sql
        ├── questions/                ← Auto-generated
        │   └── parsed_questions_my_answer_key.sql.md
        └── [student submissions]
```

## 🎯 Key Features

| Feature | Description |
|---------|-------------|
| **Smart Comparison** | LLM understands equivalent answers |
| **Fair Grading** | Accepts different approaches if correct |
| **Auto Scoring** | Extracts 0-100 scores from LLM response |
| **Detailed Feedback** | Full LLM reasoning saved with result |
| **Flexible Format** | Works with SQL, JSON, PDF, text, etc. |

## 📊 Score Formats Supported

LLM can return scores in any of these formats:
- `Score: 85`
- `Score - 85`
- `85/100`
- `85 out of 100`
- `85%`
- `85`

All are extracted and saved as 0-100 integer.

## 🧪 Test the Feature

```bash
# Run comprehensive tests
python test_grading_with_answer_key.py

# Check results
python -c "
import json
with open('./data/results.jsonl') as f:
    for line in f:
        result = json.loads(line)
        print(f\"Score: {result['score']}, Feedback: {result['feedback'][:50]}...\")
"
```

## 📝 Result Fields

Each result in `results.jsonl`:
```json
{
  "user_id": "12335",          # Canvas user ID
  "name": "Student Name",      # Student name
  "score": 85,                 # Score 0-100
  "feedback": "...",           # LLM feedback
  "reply": "...",              # Full LLM response
  "error": null                # Error if any
}
```

## ⚙️ Configuration

Required in `.env`:
```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free
```

## 🚀 API Usage

### Grade with Answer Key
```bash
curl -X POST http://localhost:5000/api/grade \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "openrouter",
    "prompt": "Grade this",
    "course_id": "268730",
    "assignment_id": "12039643"
  }'
```

### Response
```json
{
  "ok": true,
  "summary": {
    "total": 25,
    "processed": 25,
    "errors": 0,
    "has_answer_key": true,
    "elapsed_secs": 42.5
  }
}
```

## 🎓 Example Grading

### Answer Key
```sql
-- Q1: Get all users
SELECT * FROM users;

-- Q2: Count active users
SELECT COUNT(*) FROM users WHERE active = 1;
```

### Student Submission
```sql
SELECT * FROM users;
SELECT COUNT(*) AS active_count FROM users WHERE status = 'active';
```

### LLM Evaluation
```
The student's first query is perfect - matches the answer key exactly.

For the second query, the student uses 'status' column instead of 'active' 
column and uses 'active' string value instead of 1, but the logic is correct 
and demonstrates understanding. Both variations are acceptable.

Score: 95

The student shows strong understanding of SQL with minor naming differences.
```

## ⚠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| No scores | Check `has_answer_key` in summary |
| Wrong scores | Review LLM feedback, adjust answer key |
| Slow grading | Normal (2-3 sec/submission), check API rate limits |
| No answer key | System falls back to custom prompt |

## 🔗 Related Files

- `grading.py` - Main grading logic
- `app.py` - API endpoints
- `GRADING_WITH_ANSWER_KEY.md` - Full documentation
- `test_grading_with_answer_key.py` - Test suite

## 💡 Pro Tips

1. **Clear Answer Keys** → Better parsing
2. **Simple Prompts** → Faster scoring  
3. **Review First** → Check a few results
4. **Backup Scores** → Save results.jsonl regularly

## 📞 Support

For issues with:
- **Parsing**: Check answer key format/quality
- **Scoring**: Review LLM feedback in results
- **Speed**: Consider batch processing
- **API**: Verify OpenRouter key and model