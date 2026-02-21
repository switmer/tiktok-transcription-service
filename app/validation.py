"""
Input validation middleware and utilities for secure API operations
"""
import re
import logging
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

try:
    from .core.errors import ApiError, VALIDATION_ERROR
except ImportError:
    from core.errors import ApiError, VALIDATION_ERROR
from pydantic import BaseModel, validator

logger = logging.getLogger(__name__)

# Allowed video platforms and their domain patterns
ALLOWED_VIDEO_DOMAINS = {
    'tiktok': [
        'tiktok.com',
        'www.tiktok.com',
        'm.tiktok.com',
        'vm.tiktok.com'
    ],
    'youtube': [
        'youtube.com',
        'www.youtube.com',
        'm.youtube.com',
        'youtu.be',
        'music.youtube.com'
    ]
}

# Phone number patterns
PHONE_PATTERNS = {
    'us': re.compile(r'^\+1[0-9]{10}$'),  # +1XXXXXXXXXX
    'normalized': re.compile(r'^[0-9]{10}$'),  # XXXXXXXXXX (to be normalized)
    'international': re.compile(r'^\+[1-9][0-9]{1,14}$')  # Basic international format
}

# URL validation patterns
URL_PATTERNS = {
    'tiktok_video': re.compile(r'https?://(www\.|vm\.|m\.)?tiktok\.com/.+'),
    'youtube_video': re.compile(r'https?://(www\.|m\.)?(youtube\.com/watch\?v=|youtu\.be/)[a-zA-Z0-9_-]+'),
    'youtube_shorts': re.compile(r'https?://(www\.)?youtube\.com/shorts/[a-zA-Z0-9_-]+')
}

class ValidationError(Exception):
    """Custom validation error with detailed messages"""
    def __init__(self, message: str, field: str = None, code: str = None):
        self.message = message
        self.field = field
        self.code = code
        super().__init__(message)

class VideoURLValidator:
    """Validates and normalizes video URLs"""
    
    @staticmethod
    def is_valid_video_url(url: str) -> bool:
        """Check if URL is from an allowed video platform"""
        if not url or not isinstance(url, str):
            return False
            
        try:
            parsed = urlparse(url.lower())
            domain = parsed.netloc.lower()
            
            # Remove 'www.' prefix for comparison
            domain = domain.replace('www.', '')
            
            # Check against allowed domains
            for platform, domains in ALLOWED_VIDEO_DOMAINS.items():
                for allowed_domain in domains:
                    clean_allowed = allowed_domain.replace('www.', '')
                    if domain == clean_allowed or domain.endswith('.' + clean_allowed):
                        return True
                        
            return False
            
        except Exception as e:
            logger.warning(f"URL validation error for {url}: {e}")
            return False
    
    @staticmethod
    def get_platform_from_url(url: str) -> Optional[str]:
        """Determine platform (tiktok/youtube) from URL"""
        if not url:
            return None
            
        url_lower = url.lower()
        
        if 'tiktok.com' in url_lower:
            return 'tiktok'
        elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        
        return None
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL to standard format"""
        if not url:
            raise ValidationError("URL cannot be empty", "url", "EMPTY_URL")
        
        # Remove tracking parameters and normalize
        url = url.strip()
        
        # Basic URL cleanup
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        # Platform-specific normalization
        platform = VideoURLValidator.get_platform_from_url(url)
        
        if platform == 'tiktok':
            # Remove TikTok tracking parameters
            url = re.sub(r'[?&](is_from_webapp|sender_device|web_id)=[^&]*', '', url)
            url = re.sub(r'[?&]$', '', url)  # Remove trailing ? or &
            
        elif platform == 'youtube':
            # Extract video ID and create clean URL
            video_id = None
            if 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[-1].split('?')[0].split('&')[0]
            elif 'watch?v=' in url:
                video_id = url.split('watch?v=')[-1].split('&')[0]
            elif '/shorts/' in url:
                video_id = url.split('/shorts/')[-1].split('?')[0]
                
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
        
        return url
    
    @staticmethod
    def validate_and_normalize(url: str) -> str:
        """Validate and normalize video URL"""
        if not url:
            raise ValidationError("Video URL is required", "url", "MISSING_URL")
        
        # Normalize first
        try:
            normalized_url = VideoURLValidator.normalize_url(url)
        except Exception as e:
            raise ValidationError(f"Invalid URL format: {str(e)}", "url", "INVALID_FORMAT")
        
        # Then validate
        if not VideoURLValidator.is_valid_video_url(normalized_url):
            platform_list = ', '.join(ALLOWED_VIDEO_DOMAINS.keys())
            raise ValidationError(
                f"URL must be from supported platforms: {platform_list}", 
                "url", 
                "UNSUPPORTED_PLATFORM"
            )
        
        return normalized_url

class PhoneNumberValidator:
    """Validates and normalizes phone numbers"""
    
    @staticmethod
    def normalize_phone_number(phone: str) -> str:
        """Normalize phone number to +1XXXXXXXXXX format"""
        if not phone:
            raise ValidationError("Phone number is required", "phone", "MISSING_PHONE")
        
        # Remove all non-digit characters
        digits = re.sub(r'[^\d]', '', phone)
        
        # Handle different formats
        if len(digits) == 10:
            # Assume US number, add +1
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            # US number with country code
            return f"+{digits}"
        elif len(digits) >= 10:
            # International number
            return f"+{digits}"
        else:
            raise ValidationError(
                "Phone number must be at least 10 digits", 
                "phone", 
                "INVALID_LENGTH"
            )
    
    @staticmethod
    def validate_us_phone(phone: str) -> bool:
        """Validate US phone number format"""
        return bool(PHONE_PATTERNS['us'].match(phone))

class APIKeyValidator:
    """Validates API keys and related authentication"""
    
    @staticmethod
    def validate_api_key_format(api_key: str) -> bool:
        """Validate API key format (basic check)"""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # Basic format validation - adjust based on your key format
        return len(api_key) >= 32 and api_key.isalnum()

class ContentValidator:
    """Validates content fields like titles, descriptions, etc."""
    
    @staticmethod
    def sanitize_text(text: str, max_length: int = 1000) -> str:
        """Sanitize and truncate text content"""
        if not text:
            return ""
        
        # Remove/replace potentially dangerous characters
        text = text.strip()
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)  # Remove control chars
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length] + "..."
        
        return text
    
    @staticmethod
    def validate_task_id(task_id: str) -> bool:
        """Validate UUID format for task IDs"""
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        return bool(uuid_pattern.match(task_id))

class RateLimitValidator:
    """Rate limiting validation utilities"""
    
    # Simple in-memory rate limiting (for production, use Redis)
    _request_counts: Dict[str, Dict[str, int]] = {}
    
    @classmethod
    def check_rate_limit(cls, identifier: str, limit: int = 5, window: int = 60) -> bool:
        """Simple rate limiting check"""
        import time
        
        current_time = int(time.time())
        window_start = current_time - window
        
        # Clean old entries
        if identifier in cls._request_counts:
            cls._request_counts[identifier] = {
                k: v for k, v in cls._request_counts[identifier].items() 
                if int(k) > window_start
            }
        
        # Count requests in current window
        if identifier not in cls._request_counts:
            cls._request_counts[identifier] = {}
        
        request_count = sum(cls._request_counts[identifier].values())
        
        if request_count >= limit:
            return False
        
        # Record this request
        cls._request_counts[identifier][str(current_time)] = (
            cls._request_counts[identifier].get(str(current_time), 0) + 1
        )
        
        return True

# Pydantic models with validation
class ValidatedTranscriptionRequest(BaseModel):
    """Transcription request with validation"""
    url: str
    callback_url: Optional[str] = None
    
    @validator('url')
    def validate_url(cls, v):
        return VideoURLValidator.validate_and_normalize(v)
    
    @validator('callback_url')
    def validate_callback_url(cls, v):
        if v:
            # Basic URL validation for callback
            parsed = urlparse(v)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid callback URL format")
        return v

class ValidatedSMSRequest(BaseModel):
    """SMS request with validation"""
    From: str
    Body: str
    
    @validator('From')
    def validate_phone(cls, v):
        return PhoneNumberValidator.normalize_phone_number(v)
    
    @validator('Body')
    def validate_body(cls, v):
        return ContentValidator.sanitize_text(v, max_length=1600)  # SMS limit

# Middleware functions
def validate_request_size(content_length: int, max_size: int = 10 * 1024 * 1024):
    """Validate request size (10MB default)"""
    if content_length > max_size:
        raise ApiError(
            413, VALIDATION_ERROR,
            f"Request too large. Maximum size: {max_size // (1024*1024)}MB"
        )

def validate_content_type(content_type: str, allowed_types: List[str]):
    """Validate request content type"""
    if content_type not in allowed_types:
        raise ApiError(
            415, VALIDATION_ERROR,
            f"Unsupported content type. Allowed: {', '.join(allowed_types)}"
        )

# Security headers
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin"
}

def add_security_headers(response):
    """Add security headers to response"""
    for header, value in SECURITY_HEADERS.items():
        response.headers[header] = value
    return response

# Export main validation functions
__all__ = [
    'VideoURLValidator',
    'PhoneNumberValidator', 
    'APIKeyValidator',
    'ContentValidator',
    'RateLimitValidator',
    'ValidatedTranscriptionRequest',
    'ValidatedSMSRequest',
    'ValidationError',
    'validate_request_size',
    'validate_content_type',
    'add_security_headers'
]