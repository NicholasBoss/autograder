#!/usr/bin/env python3
"""
Test script to verify folder structure creation
"""
import json
import requests
from pathlib import Path
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_folder_creation():
    """Test the fetch_submissions endpoint to ensure proper folder creation"""
    
    # Test data
    test_data = {
        "course_id": "268730",
        "assignment_id": "12039643",
        "download_files": False  # Don't actually download files for this test
    }
    
    print("🧪 Testing folder structure creation...")
    print(f"Course ID: {test_data['course_id']}")
    print(f"Assignment ID: {test_data['assignment_id']}")
    
    # Expected folder structure
    base_download_dir = Path("./data/downloads")
    expected_course_dir = base_download_dir / f"course_{test_data['course_id']}"
    expected_assignment_dir = expected_course_dir / f"assignment_{test_data['assignment_id']}"
    expected_answer_key_dir = expected_assignment_dir / "answer_key"
    expected_questions_dir = expected_assignment_dir / "questions"
    
    print(f"\n📁 Expected folder structure:")
    print(f"   Course folder: {expected_course_dir}")
    print(f"   Assignment folder: {expected_assignment_dir}")
    print(f"   Answer key folder: {expected_answer_key_dir}")
    print(f"   Questions folder: {expected_questions_dir}")
    
    # Make request to fetch_submissions endpoint
    try:
        response = requests.post(
            "http://localhost:5000/api/fetch-submissions",
            json=test_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        print(f"\n📡 API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ API call successful")
            print(f"   Total submissions: {result.get('total_submissions', 'N/A')}")
            print(f"   Downloaded files: {result.get('downloaded_files', 'N/A')}")
        else:
            print(f"❌ API call failed: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False
    
    # Check if folders were created
    print(f"\n🔍 Checking folder creation...")
    
    folders_to_check = [
        ("Course", expected_course_dir),
        ("Assignment", expected_assignment_dir),
        ("Answer Key", expected_answer_key_dir),
        ("Questions", expected_questions_dir)
    ]
    
    all_folders_exist = True
    for folder_name, folder_path in folders_to_check:
        if folder_path.exists() and folder_path.is_dir():
            print(f"   ✅ {folder_name} folder exists: {folder_path}")
        else:
            print(f"   ❌ {folder_name} folder missing: {folder_path}")
            all_folders_exist = False
    
    if all_folders_exist:
        print(f"\n🎉 SUCCESS: All expected folders were created!")
        
        # List contents of assignment folder
        print(f"\n📂 Contents of assignment folder:")
        try:
            for item in expected_assignment_dir.iterdir():
                if item.is_dir():
                    print(f"   📁 {item.name}/")
                else:
                    print(f"   📄 {item.name}")
        except Exception as e:
            print(f"   Error listing contents: {e}")
            
        return True
    else:
        print(f"\n❌ FAILURE: Some folders were not created properly!")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 FOLDER STRUCTURE TEST")
    print("=" * 60)
    
    # Check if Flask app is running
    try:
        response = requests.get("http://localhost:5000/", timeout=5)
        print("✅ Flask app is running")
    except requests.exceptions.RequestException:
        print("❌ Flask app is not running. Please start it with 'python app.py' or 'flask run'")
        exit(1)
    
    success = test_folder_creation()
    
    print("=" * 60)
    if success:
        print("🎉 TEST PASSED: Folder structure creation works correctly!")
    else:
        print("❌ TEST FAILED: Folder structure creation has issues!")
    print("=" * 60)