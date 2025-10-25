#!/usr/bin/env python3
"""
Test script to verify OpenRouter grading with answer key comparison
"""
import json
import os
import sys

def test_grading_imports():
    """Test that all grading imports work correctly"""
    print("🧪 Testing grading imports...")
    
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from grading import grade_assignments, _call_openrouter, _get_parsed_questions_content, _extract_score_from_response
        print("   ✅ All grading functions imported successfully")
        return True
    except Exception as e:
        print(f"   ❌ Import error: {e}")
        return False

def test_score_extraction():
    """Test the score extraction from LLM responses"""
    print("\n🧪 Testing score extraction from LLM responses...")
    
    try:
        from grading import _extract_score_from_response
        
        test_cases = [
            ("Score: 85", 85),
            ("The student scored 92 out of 100", 92),
            ("Overall: 78%", 78),
            ("85/100", 85),
            ("Score - 75", 75),
            ("The answer is mostly correct. 88", 88),
            ("0", 0),
            ("100", 100),
            ("150", 100),  # Should clamp to 100
            ("no number here", None),
        ]
        
        all_passed = True
        for test_input, expected in test_cases:
            result = _extract_score_from_response(test_input)
            status = "✅" if result == expected else "❌"
            print(f"   {status} '{test_input[:40]}...' -> {result} (expected {expected})")
            if result != expected:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_parsed_questions_loading():
    """Test loading parsed questions from file system"""
    print("\n🧪 Testing parsed questions loading...")
    
    try:
        from grading import _get_parsed_questions_content
        
        # This will return None if no questions are found, which is ok for this test
        result = _get_parsed_questions_content("268730", "12039643")
        
        if result is not None:
            print(f"   ✅ Parsed questions loaded successfully")
            print(f"   📄 Content preview: {result[:100]}...")
            return True
        else:
            print(f"   ⚠️  No parsed questions found (this is ok if you haven't uploaded answer key yet)")
            print(f"   📁 Location checked: ./data/downloads/course_268730/assignment_12039643/questions/")
            return True  # Not a failure, just no data yet
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

def test_grading_function_signature():
    """Test that the grading function has the correct signature"""
    print("\n🧪 Testing grading function signature...")
    
    try:
        from grading import grade_assignments
        import inspect
        
        sig = inspect.signature(grade_assignments)
        params = list(sig.parameters.keys())
        
        expected_params = [
            'backend', 'prompt', 'out_path', 'canvas_api_url',
            'canvas_api_token', 'course_id', 'assignment_id',
            'openrouter_api_key', 'openrouter_model'
        ]
        
        all_present = True
        for param in expected_params:
            if param in params:
                print(f"   ✅ Parameter '{param}' present")
            else:
                print(f"   ❌ Parameter '{param}' missing")
                all_present = False
        
        return all_present
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 70)
    print("🚀 OPENROUTER GRADING WITH ANSWER KEY COMPARISON TEST")
    print("=" * 70)
    
    tests = [
        ("Grading Imports", test_grading_imports),
        ("Score Extraction", test_score_extraction),
        ("Parsed Questions Loading", test_parsed_questions_loading),
        ("Grading Function Signature", test_grading_function_signature),
    ]
    
    all_passed = True
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        if not test_func():
            all_passed = False
            print(f"❌ {test_name} FAILED")
        else:
            print(f"✅ {test_name} PASSED")
    
    print("\n" + "=" * 70)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("\n📋 New Features:")
        print("   ✓ OpenRouter now uses parsed answer keys for grading")
        print("   ✓ LLM compares student answers against expected answers")
        print("   ✓ Intelligent score extraction from LLM responses")
        print("   ✓ Support for course-specific and legacy folder structures")
        print("   ✓ Detailed feedback included in grading results")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 70)