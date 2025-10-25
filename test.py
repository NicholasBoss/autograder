import requests
import os
from dotenv import load_dotenv

# Load env vars
load_dotenv()

# Test if we have the required environment variables
canvas_url = os.getenv('CANVAS_API_URL', 'https://canvas.instructure.com')
canvas_token = os.getenv('CANVAS_API_TOKEN')

print(f'Canvas URL: {canvas_url}')
# Fix the f-string syntax error by using a different approach
token_display = '*' * len(canvas_token) if canvas_token else 'Not set'
print(f'Canvas Token: {token_display}')

if canvas_token:
    print('Testing Canvas API connection...')
    headers = {'Authorization': f'Bearer {canvas_token}'}
    try:
        response = requests.get(f'{canvas_url}/users/self', headers=headers, timeout=10)
        if response.status_code == 200:
            user = response.json()
            print(f'✅ Successfully connected to Canvas as: {user.get("name", "Unknown")}')
        else:
            print(f'❌ Canvas API error: {response.status_code} - {response.text}')
    except Exception as e:
        print(f'❌ Connection error: {e}')
else:
    print('❌ Canvas API token not found in environment variables')
