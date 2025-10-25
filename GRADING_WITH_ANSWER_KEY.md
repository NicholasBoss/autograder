# OpenRouter Grading with Answer Key Comparison

## Overview

The autograder now uses OpenRouter's LLM to intelligently grade student submissions by comparing them against parsed answer keys. This provides fair and flexible evaluation that accepts correct answers even when worded differently.

## How It Works

### 1. **Answer Key Processing**
- Upload an answer key (SQL, JSON, PDF, etc.) through the Upload Answer Key page
- The system uses OpenRouter to parse the answer key into structured questions and answers
- Parsed questions are saved in markdown format for reference

### 2. **Intelligent Grading**
- When grading submissions, the system retrieves the parsed questions and answers
- The LLM receives both the answer key and student submission
- The LLM evaluates if the student's answer would work with the expected answers
- Provides fair assessment even for variations in approach

### 3. **Score Extraction**
- The LLM provides grading feedback with a numerical score
- The system extracts scores from responses in multiple formats:
  - `Score: 85`
  - `85 out of 100`
  - `85%`
  - `85/100`

## Data Flow

```
Answer Key
    ↓
[OpenRouter AI] → Parsed Questions (Markdown)
    ↓
Student Submissions
    ↓
[Get Student Text from Files]
    ↓
[OpenRouter AI + Parsed Questions] → Evaluation & Score
    ↓
Results (score, feedback)
```

## File Structure

```
data/downloads/
└── course_{course_id}/
    └── assignment_{assignment_id}/
        ├── answer_key/
        │   └── [uploaded_answer_key_file]
        ├── questions/
        │   └── parsed_questions_*.md  ← Used for grading
        └── [student_submissions]
```

## Key Features

### ✨ Flexible Grading
- Accepts correct answers in different formats/styles
- Understands SQL query variations, different wording, etc.
- Provides constructive feedback on partial correctness

### 🎯 Accurate Scoring
- 0-100 scale scores
- Automatic score extraction from LLM responses
- Handles edge cases and malformed responses

### 📊 Comprehensive Feedback
- Returns LLM analysis and reasoning
- Includes feedback about correctness
- Stored in results for review

### 🔄 Fallback Support
- Works with or without parsed answer keys
- Falls back to custom prompt if no answer key available
- Graceful error handling

## Configuration

### Required Environment Variables
```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=meta-llama/llama-3.1-8b-instruct:free  # or your preferred model
```

### API Endpoint

**POST** `/api/grade`

Request payload:
```json
{
  "backend": "openrouter",
  "prompt": "Your custom grading prompt (optional if answer key exists)",
  "course_id": "268730",
  "assignment_id": "12039643"
}
```

Response:
```json
{
  "ok": true,
  "summary": {
    "counts": {
      "processed": 25,
      "errors": 2,
      "no_text": 1
    },
    "elapsed_secs": 45.3,
    "backend": "openrouter",
    "out_path": "./data/results.jsonl",
    "total": 28,
    "has_answer_key": true
  }
}
```

## Result Format

Each result in `results.jsonl`:
```json
{
  "course_id": "268730",
  "assignment_id": "12039643",
  "user_id": "12345",
  "name": "John Doe",
  "reply": "[Full LLM response with evaluation]",
  "score": 85,
  "feedback": "[Grading feedback from LLM]",
  "error": null
}
```

## System Prompt

When an answer key is available, the system uses this prompt template:

```
You are an expert grader evaluating student submissions against a provided answer key.

Your task is to:
1. Compare the student's submission against the expected answers
2. Determine if the student's answer is correct, partially correct, or incorrect
3. Provide a numerical score as a percentage (0-100)
4. Explain your reasoning

Be fair and flexible - accept answers that demonstrate understanding of the 
concepts, even if they're worded differently from the answer key.

ANSWER KEY AND EXPECTED ANSWERS:
[Parsed questions and answers in markdown format]

Evaluate the student's submission below and provide:
- A score (0-100)
- Brief feedback explaining the score
```

## Workflow Example

### Step 1: Upload Answer Key
1. Go to "Upload Answer Key" page
2. Select course and assignment
3. Upload answer key file (SQL, JSON, PDF, etc.)
4. Click "Parse Questions"

### Step 2: Check Parsed Questions
- Questions are parsed and saved to `course_{id}/assignment_{id}/questions/`
- Review in "Questions Analysis" page

### Step 3: Grade Submissions
1. Go to "Assignments" page
2. Select course and assignment
3. Click "Start Grading"
4. Grading uses parsed questions automatically

### Step 4: Review Results
1. Go to "Performance" page
2. View student scores
3. See detailed feedback from LLM

## Error Handling

- **No answer key found**: System falls back to custom prompt
- **Empty submission**: Score = 0, feedback = "No submission text found"
- **API errors**: Caught and logged, result marked with error message
- **Score extraction failed**: Returns None, marked for review

## Best Practices

1. **Clear Answer Keys**: More structured answer keys → better parsing
2. **Descriptive Prompts**: If using fallback, provide clear grading criteria
3. **Regular Review**: Check a few results to verify quality
4. **Reasonable Timeouts**: API calls may take 5-30 seconds per submission

## Troubleshooting

### No scores appearing
- Check `has_answer_key` in summary
- Verify parsed questions file exists
- Check OpenRouter API key is valid

### Incorrect scores
- Review LLM feedback in results
- Consider uploading a clearer answer key
- Adjust custom prompt if not using answer key

### Slow grading
- Normal for 20-50 submissions (1-2 minutes)
- OpenRouter API rate limits may apply
- Consider breaking into smaller batches

## Technical Details

### Score Extraction Patterns
The system tries to find scores in this order:
1. `score: 85` or `score - 85` (case-insensitive)
2. `85 out of 100` or `85/100`
3. `85%`
4. Just the number `85`

Scores are clamped to 0-100 range.

### Supported File Types
- SQL files (.sql)
- Text files (.txt)
- PDF files (.pdf)
- DOCX files (.docx)
- Markdown files (.md)
- JSON files (.json)

## Example Grading Session

```
Input Answer Key:
- Q1: Write a SELECT query that...
- A1: SELECT * FROM table WHERE...

Student Submission:
SELECT col1, col2 FROM table WHERE id > 5

OpenRouter Output:
"The student's query is correct. It uses appropriate syntax 
and would return the expected results. The approach is slightly 
different from the answer key but demonstrates understanding.
Score: 90"

Extracted Score: 90
```