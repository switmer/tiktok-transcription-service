#!/usr/bin/env python3
"""
Example script demonstrating how to use the TikTok API adapter pattern.

This script shows how the system automatically handles:
1. Rate limiting across multiple APIs
2. Failover when APIs hit limits or fail
3. Monitoring adapter status

Setup:
1. Set environment variables in .env:
   RAPIDAPI_KEYS=key1,key2,key3
   RAPIDAPI_HOSTS=host1,host2,host3
   RAPIDAPI_V2_KEYS=v2_key1,v2_key2
   RAPIDAPI_V2_HOSTS=tiktok-scraper2.p.rapidapi.com
   ENABLE_TIKWM=true

2. Run: python example_tiktok_adapter_usage.py
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

# Add the current directory to the path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Load environment variables
load_dotenv()

from tiktok_service import tiktok_service
from adapters.config import get_adapter_config_info

def print_config_info():
    """Print current adapter configuration."""
    print("🔧 TikTok API Adapter Configuration:")
    print("=" * 50)
    
    config = get_adapter_config_info()
    print(f"RapidAPI v1 Keys Configured: {config['rapidapi_keys_configured']}")
    print(f"RapidAPI v1 Hosts: {config['rapidapi_hosts'] or ['tiktok-scraper7.p.rapidapi.com (default)']}")
    print(f"RapidAPI v2 Keys Configured: {config['rapidapi_v2_keys_configured']}")
    print(f"RapidAPI v2 Hosts: {config['rapidapi_v2_hosts'] or ['tiktok-scraper2.p.rapidapi.com (default)']}")
    print(f"TikWM Enabled: {config['tikwm_enabled']}")
    print()
    
    for key, value in config['environment_variables'].items():
        print(f"{key}: {value}")
    print()

def print_adapters_status():
    """Print status of all adapters."""
    print("📊 Adapters Status:")
    print("=" * 50)
    
    status = tiktok_service.get_adapters_status()
    print(f"Total Adapters: {status['total_adapters']}")
    print(f"Available Adapters: {status['available_adapters']}")
    print(f"Current Adapter: {status['current_adapter'] or 'None'}")
    print()
    
    for adapter in status['adapters']:
        print(f"📡 {adapter['name']}")
        print(f"   Available: {'✅' if adapter['available'] else '❌'}")
        
        if adapter['rate_limit_info']:
            rl = adapter['rate_limit_info']
            print(f"   Rate Limit: {rl['remaining']}/{rl['limit']} remaining")
            print(f"   Reset Time: {rl['reset_time']}")
            print(f"   Exhausted: {'⚠️' if rl['is_exhausted'] else '✅'}")
        else:
            print(f"   Rate Limit: No info available")
        print()

def test_video_info(video_url: str):
    """Test getting video info with automatic failover."""
    print(f"🎬 Testing Video Info Retrieval:")
    print(f"URL: {video_url}")
    print("=" * 50)
    
    result = tiktok_service.get_video_info(video_url)
    
    if result['success']:
        print("✅ Success!")
        data = result['data']
        
        # Extract common fields that might be present
        if data:
            print(f"Title: {data.get('title', 'N/A')}")
            print(f"Author: {data.get('author', {}).get('nickname', 'N/A')}")
            print(f"Duration: {data.get('duration', 'N/A')} seconds")
            print(f"Views: {data.get('view_count', 'N/A')}")
            
        if result.get('rate_limit_info'):
            rl = result['rate_limit_info']
            print(f"Rate Limit Used: {rl['remaining']}/{rl['limit']} remaining")
    else:
        print("❌ Failed!")
        print(f"Error: {result['error']}")
        
        if result.get('status_code'):
            print(f"Status Code: {result['status_code']}")
    
    print()

def simulate_rate_limit_scenario():
    """Simulate hitting rate limits to show failover behavior."""
    print("🔄 Simulating Rate Limit Scenario:")
    print("=" * 50)
    
    # Test with multiple requests to potentially hit rate limits
    test_urls = [
        "https://www.tiktok.com/@user/video/1234567890",  # These are example URLs
        "https://www.tiktok.com/@user/video/1234567891",
        "https://www.tiktok.com/@user/video/1234567892",
    ]
    
    for i, url in enumerate(test_urls, 1):
        print(f"Request {i}:")
        result = tiktok_service.get_video_info(url)
        
        if result['success']:
            print(f"  ✅ Success with adapter")
        else:
            print(f"  ❌ Failed: {result['error']}")
        
        # Show current adapter status after each request
        status = tiktok_service.get_adapters_status()
        print(f"  Current adapter: {status['current_adapter']}")
        print(f"  Available adapters: {status['available_adapters']}/{status['total_adapters']}")
        print()

def main():
    """Main demonstration function."""
    print("🚀 TikTok API Adapter Pattern Demo")
    print("=" * 50)
    print()
    
    # Show configuration
    print_config_info()
    
    # Show initial adapter status
    print_adapters_status()
    
    # Test with a real TikTok URL (you can replace this)
    # Note: Using example URL - replace with actual TikTok URL for real testing
    test_url = "https://www.tiktok.com/@example/video/1234567890"
    
    print("⚠️  Note: Replace with a real TikTok URL for actual testing")
    print(f"Using example URL: {test_url}")
    print()
    
    # Test basic functionality
    test_video_info(test_url)
    
    # Show adapter status after test
    print_adapters_status()
    
    print("🎯 Key Features Demonstrated:")
    print("• Automatic failover between multiple APIs")
    print("• Rate limit detection and handling")
    print("• Real-time adapter status monitoring")
    print("• Environment-based configuration")
    print()
    
    print("🔗 API Endpoints Available:")
    print("• GET /api/public/tiktok/video-info?video_url=...")
    print("• GET /api/public/tiktok/adapters-status")
    print("• POST /api/tiktok/refresh-adapters (requires API key)")

if __name__ == "__main__":
    main()