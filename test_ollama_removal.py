#!/usr/bin/env python3
"""
Test script to verify Ollama removal and OpenRouter functionality
"""
import sys
import os

def test_imports():
    """Test that all imports work correctly after Ollama removal"""
    print("🧪 Testing imports...")
    
    try:
        # Test app.py imports
        sys.path.insert(0, os.path.dirname(__file__))
        from app import APP, load_env
        print("   ✅ app.py imports successful")
        
        # Test grading.py imports
        from grading import grade_assignments, _call_openrouter
        print("   ✅ grading.py imports successful")
        
        # Test that the function signature is correct
        import inspect
        sig = inspect.signature(grade_assignments)
        params = list(sig.parameters.keys())
        
        expected_params = [
            'backend', 'prompt', 'out_path', 'canvas_api_url', 
            'canvas_api_token', 'course_id', 'assignment_id',
            'openrouter_api_key', 'openrouter_model'
        ]
        
        for param in expected_params:
            if param in params:
                print(f"   ✅ Parameter '{param}' found")
            else:
                print(f"   ❌ Parameter '{param}' missing")
                return False
        
        # Check that ollama parameters are NOT present
        ollama_params = ['ollama_host', 'ollama_model']
        for param in ollama_params:
            if param in params:
                print(f"   ❌ Ollama parameter '{param}' still present")
                return False
            else:
                print(f"   ✅ Ollama parameter '{param}' removed")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Import error: {e}")
        return False

def test_config():
    """Test that configuration loads without Ollama references"""
    print("\n🧪 Testing configuration...")
    
    try:
        from app import load_env, DEFAULTS
        
        # Check that OLLAMA keys are not in DEFAULTS
        ollama_keys = ['OLLAMA_HOST', 'OLLAMA_MODEL']
        for key in ollama_keys:
            if key in DEFAULTS:
                print(f"   ❌ Ollama default '{key}' still present")
                return False
            else:
                print(f"   ✅ Ollama default '{key}' removed")
        
        # Check that OpenRouter keys are present
        openrouter_keys = ['OPENROUTER_MODEL']
        for key in openrouter_keys:
            if key in DEFAULTS:
                print(f"   ✅ OpenRouter default '{key}' present")
            else:
                print(f"   ❌ OpenRouter default '{key}' missing")
                return False
        
        return True
        
    except Exception as e:
        print(f"   ❌ Config error: {e}")
        return False

def test_backend_support():
    """Test that only OpenRouter backend is supported"""
    print("\n🧪 Testing backend support...")
    
    try:
        from grading import grade_assignments
        import inspect
        
        # Get the backend parameter type hint
        sig = inspect.signature(grade_assignments)
        backend_param = sig.parameters['backend']
        
        # Check if it's a Literal type with only "openrouter"
        if hasattr(backend_param.annotation, '__args__'):
            supported_backends = backend_param.annotation.__args__
            if supported_backends == ("openrouter",):
                print("   ✅ Only OpenRouter backend supported")
                return True
            else:
                print(f"   ❌ Unexpected backends: {supported_backends}")
                return False
        else:
            print("   ❌ Backend parameter type hint not found")
            return False
            
    except Exception as e:
        print(f"   ❌ Backend test error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 OLLAMA REMOVAL TEST")
    print("=" * 60)
    
    tests = [
        ("Import Test", test_imports),
        ("Configuration Test", test_config),
        ("Backend Support Test", test_backend_support)
    ]
    
    all_passed = True
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name}...")
        if not test_func():
            all_passed = False
            print(f"❌ {test_name} FAILED")
        else:
            print(f"✅ {test_name} PASSED")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED: Ollama successfully removed!")
        print("   - All imports work correctly")
        print("   - Configuration cleaned up")
        print("   - Only OpenRouter backend supported")
    else:
        print("❌ SOME TESTS FAILED: Issues remain with Ollama removal")
    print("=" * 60)