"""
Test configuration and fixtures for the transcription service test suite.
Provides database setup, mock clients, and shared test utilities.
"""
import pytest
import asyncio
import os
import uuid
from typing import Dict, Any, Optional
from unittest.mock import Mock, AsyncMock
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import app components
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import supabase
from app import app
from fastapi.testclient import TestClient

# Test configuration
TEST_PHONE_NUMBER = "+15551234567"
TEST_USER_PHONE = "+15559876543"
TEST_VIDEO_URL = "https://tiktok.com/@test/video/123456789"
TEST_TASK_ID = "550e8400-e29b-41d4-a716-446655440000"

@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for testing"""
    mock_client = Mock()
    
    # Mock table responses
    mock_table = Mock()
    mock_client.table.return_value = mock_table
    
    # Mock RPC responses
    mock_client.rpc.return_value.execute.return_value = Mock(data=[])
    
    return mock_client

@pytest.fixture
def sample_sms_user():
    """Sample SMS user for testing"""
    return {
        "id": str(uuid.uuid4()),
        "phone_number": TEST_USER_PHONE,
        "phone_verified": True,
        "credits_remaining": 5,
        "free_credits_used": 0,
        "total_credits_purchased": 0,
        "total_videos_transcribed": 0,
        "referral_code": "ABC123",
        "created_at": datetime.now().isoformat(),
        "last_active": datetime.now().isoformat()
    }

@pytest.fixture
def sample_transcription():
    """Sample transcription record for testing"""
    return {
        "task_id": TEST_TASK_ID,
        "user_phone": TEST_USER_PHONE,
        "url": TEST_VIDEO_URL,
        "status": "completed",
        "title": "Test Video Title",
        "video_id": "123456789",
        "platform": "tiktok",
        "transcript": "This is a test transcript of the video content.",
        "quote": "This is the most quotable line from the video.",
        "tldr": ["Key point 1", "Key point 2", "Key point 3"],
        "like_count": 1500,
        "view_count": 25000,
        "thumbnail_url": "https://cdn.tiktok.com/thumbnail.jpg",
        "supabase_thumbnail_url": "https://storage.supabase.co/thumbnail.jpg",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }

@pytest.fixture
def sample_user_message():
    """Sample user message for testing"""
    return {
        "id": str(uuid.uuid4()),
        "from_phone": TEST_USER_PHONE,
        "to_phone": TEST_PHONE_NUMBER,
        "message_body": TEST_VIDEO_URL,
        "message_sid": f"SM{uuid.uuid4().hex[:32]}",
        "direction": "inbound",
        "command": "video_url",
        "created_at": datetime.now().isoformat()
    }

@pytest.fixture
def mock_twilio_client():
    """Mock Twilio client for SMS testing"""
    mock_client = Mock()
    
    # Mock message creation
    mock_message = Mock()
    mock_message.sid = f"SM{uuid.uuid4().hex[:32]}"
    mock_message.status = "sent"
    
    mock_client.messages.create.return_value = mock_message
    
    return mock_client

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for transcription testing"""
    mock_client = Mock()
    
    # Mock Whisper API response
    mock_transcription = Mock()
    mock_transcription.text = "This is a test transcript from OpenAI Whisper."
    
    mock_client.audio.transcriptions.create.return_value = mock_transcription
    
    # Mock GPT-4 response for enrichment
    mock_completion = Mock()
    mock_completion.choices = [Mock()]
    mock_completion.choices[0].message.content = '{"quote": "Test quote", "tldr": ["Point 1", "Point 2"]}'
    
    mock_client.chat.completions.create.return_value = mock_completion
    
    return mock_client

@pytest.fixture
async def clean_test_data():
    """Clean up test data before and after tests"""
    if supabase is None:
        pytest.skip("Supabase client not available")
    
    # Clean up any existing test data
    await cleanup_test_phone_numbers()
    
    yield
    
    # Clean up after test
    await cleanup_test_phone_numbers()

async def cleanup_test_phone_numbers():
    """Remove test phone numbers from all tables"""
    if supabase is None:
        return
        
    test_phones = [TEST_USER_PHONE, TEST_PHONE_NUMBER]
    
    try:
        # Clean up in reverse FK dependency order
        for phone in test_phones:
            # Clean transcriptions (SET NULL on FK)
            supabase.table('transcriptions').update({'user_phone': None}).eq('user_phone', phone).execute()
            
            # Clean user_messages (CASCADE on FK)
            supabase.table('user_messages').delete().eq('from_phone', phone).execute()
            
            # Clean credit_purchases (RESTRICT on FK - delete purchases first)
            supabase.table('credit_purchases').delete().eq('phone_number', phone).execute()
            
            # Clean SMS users (main table)
            supabase.table('sms_users').delete().eq('phone_number', phone).execute()
            
    except Exception as e:
        print(f"Warning: Test cleanup failed: {e}")

@pytest.fixture
def database_health_check():
    """Verify database health before critical tests"""
    if supabase is None:
        pytest.skip("Supabase client not available")
    
    try:
        # Test basic connectivity
        response = supabase.table('transcriptions').select('task_id').limit(1).execute()
        assert response is not None
        
        # Test FK integrity function
        integrity_response = supabase.rpc('check_fk_integrity').execute()
        assert integrity_response is not None
        
        return True
    except Exception as e:
        pytest.skip(f"Database health check failed: {e}")

@pytest.fixture
def mock_background_task():
    """Mock background task execution"""
    mock_bg = AsyncMock()
    return mock_bg

class TestDataBuilder:
    """Builder pattern for creating test data"""
    
    @staticmethod
    def sms_user(phone: str = TEST_USER_PHONE, credits: int = 5, **kwargs) -> Dict[str, Any]:
        """Build SMS user test data matching actual schema"""
        base = {
            "phone_number": phone,
            "phone_verified": True,
            "credits_remaining": credits,
            "free_credits_used": 0,
            "total_credits_purchased": 0,
            "total_videos_transcribed": 0,
            "referral_code": f"TEST{uuid.uuid4().hex[:6].upper()}",
            "last_active": datetime.now().isoformat(),
            # Only include fields that exist in actual schema
            "referrals_count": 0,
            "total_referral_credits_earned": 0,
            "referral_streak": 0
        }
        base.update(kwargs)
        return base
    
    @staticmethod
    def create_or_update_sms_user(phone: str = TEST_USER_PHONE, credits: int = 5, **kwargs) -> Dict[str, Any]:
        """Create or update SMS user using UPSERT to avoid conflicts"""
        if supabase is None:
            return TestDataBuilder.sms_user(phone, credits, **kwargs)
            
        user_data = TestDataBuilder.sms_user(phone, credits, **kwargs)
        
        try:
            # Try to upsert the user
            result = supabase.table('sms_users').upsert(user_data, on_conflict='phone_number').execute()
            return result.data[0] if result.data else user_data
        except Exception as e:
            print(f"Warning: Could not upsert user {phone}: {e}")
            return user_data
    
    @staticmethod
    def transcription(task_id: str = None, user_phone: str = TEST_USER_PHONE, status: str = "completed", **kwargs) -> Dict[str, Any]:
        """Build transcription test data"""
        base = {
            "task_id": task_id or str(uuid.uuid4()),
            "user_phone": user_phone,
            "url": TEST_VIDEO_URL,
            "status": status,
            "title": "Test Video Title",
            "video_id": str(uuid.uuid4().int)[:10],
            "platform": "tiktok",
            "transcript": "This is a test transcript of the video content.",
            "quote": "This is the most quotable line from the video.",
            "tldr": ["Key point 1", "Key point 2", "Key point 3"],
            "like_count": 1500,
            "view_count": 25000,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        base.update(kwargs)
        return base
    
    @staticmethod
    def user_message(from_phone: str = TEST_USER_PHONE, message_body: str = TEST_VIDEO_URL, **kwargs) -> Dict[str, Any]:
        """Build user message test data"""
        base = {
            "id": str(uuid.uuid4()),
            "from_phone": from_phone,
            "to_phone": TEST_PHONE_NUMBER,
            "message_body": message_body,
            "message_sid": f"SM{uuid.uuid4().hex[:32]}",
            "direction": "inbound",
            "command": "video_url" if "http" in message_body else "unknown",
            "created_at": datetime.now().isoformat()
        }
        base.update(kwargs)
        return base

@pytest.fixture
def test_data_builder():
    """Provide test data builder"""
    return TestDataBuilder

# Async test configuration
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# Environment setup
@pytest.fixture(autouse=True)
def setup_test_environment():
    """Ensure test environment variables are set"""
    os.environ.setdefault("TESTING", "true")
    os.environ.setdefault("LOG_LEVEL", "INFO")
    
    # Mock external API keys if not set
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "test-key"
    if not os.getenv("RAPIDAPI_KEY"):
        os.environ["RAPIDAPI_KEY"] = "test-key"