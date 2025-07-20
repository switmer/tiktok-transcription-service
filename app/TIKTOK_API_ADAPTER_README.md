# TikTok API Adapter Pattern

This system implements an adapter pattern for TikTok APIs that automatically handles rate limits and failover between multiple API providers.

## Features

- **Automatic Failover**: Seamlessly switches between different TikTok APIs when one hits rate limits or fails
- **Rate Limit Detection**: Monitors API response headers to detect and handle rate limits
- **Multiple Providers**: Supports RapidAPI providers and free APIs like TikWM
- **Real-time Monitoring**: Track adapter status and rate limit information
- **Configurable**: Easy environment-based configuration

## Setup

### 1. Environment Variables

Add these to your `.env` file:

```bash
# Multiple RapidAPI v1 keys for TikTok APIs (comma-separated)
RAPIDAPI_KEYS=your_rapidapi_key_1,your_rapidapi_key_2,your_rapidapi_key_3

# Multiple RapidAPI v1 hosts (comma-separated, optional)
RAPIDAPI_HOSTS=tiktok-scraper7.p.rapidapi.com,tiktok-video-no-watermark2.p.rapidapi.com

# Multiple RapidAPI v2 keys for TikTok Scraper v2 APIs (comma-separated)
RAPIDAPI_V2_KEYS=your_rapidapi_v2_key_1,your_rapidapi_v2_key_2

# Multiple RapidAPI v2 hosts (comma-separated, optional)
RAPIDAPI_V2_HOSTS=tiktok-scraper2.p.rapidapi.com

# Enable/disable TikWM adapter (free API, no key required)
ENABLE_TIKWM=true
```

### 2. Install Dependencies

```bash
pip install requests python-dotenv
```

## Usage

### Basic Usage

```python
from tiktok_service import tiktok_service

# Get video info with automatic failover
result = tiktok_service.get_video_info("https://www.tiktok.com/@user/video/1234567890")

if result['success']:
    print("Video data:", result['data'])
else:
    print("Error:", result['error'])
```

### API Endpoints

The system adds these endpoints to your FastAPI app:

#### Public Endpoints (No API Key Required)

- **GET** `/api/public/tiktok/video-info?video_url=...`
  - Get TikTok video information with automatic failover
  - Returns video data and rate limit info

- **GET** `/api/public/tiktok/adapters-status`
  - Get status of all configured adapters
  - Shows rate limits and availability

#### Private Endpoints (API Key Required)

- **POST** `/api/tiktok/refresh-adapters`
  - Refresh adapter configuration after env changes

### Example Usage

```bash
# Test the API adapter system
python example_tiktok_adapter_usage.py

# Get video info via API
curl "http://localhost:8000/api/public/tiktok/video-info?video_url=https://www.tiktok.com/@user/video/1234567890"

# Check adapter status
curl "http://localhost:8000/api/public/tiktok/adapters-status"
```

## How It Works

### 1. Adapter Pattern

Each API provider is wrapped in an adapter that implements a common interface:

```python
class TikTokAPIAdapter(ABC):
    def get_video_info(self, video_url: str) -> APIResponse
    def parse_rate_limit_headers(self, headers: Dict[str, str]) -> RateLimitInfo
    def is_available(self) -> bool
```

### 2. Rate Limit Detection

The system monitors response headers to detect rate limits:

- **RapidAPI**: Uses `x-ratelimit-*` headers
- **Other APIs**: Falls back to HTTP 429 status codes
- **Automatic Reset**: Re-enables adapters when rate limits reset

### 3. Failover Logic

```
Request → Adapter 1 (Available?) → Success/Fail
            ↓ (Rate Limited)
          Adapter 2 (Available?) → Success/Fail
            ↓ (Server Error)
          Adapter 3 (Available?) → Success/Fail
```

### 4. Adapter States

- **Available**: Ready to process requests
- **Rate Limited**: Temporarily disabled until reset time
- **Disabled**: Temporarily disabled due to errors
- **Failed**: Permanent failure (needs manual intervention)

## Configuration Options

### Adapter Types

1. **RapidAPI v1 Adapters**
   - Uses endpoints like `/video/info`
   - Requires API keys
   - Supports multiple hosts/providers
   - Has detailed rate limit headers

2. **RapidAPI v2 Adapters**
   - Uses endpoints like `/video/info_v2` (tiktok-scraper2)
   - More detailed video information and metadata
   - Better video quality options and bitrate info
   - Includes subtitle/caption support
   - Requires API keys and supports multiple hosts

3. **TikWM Adapter**
   - Free to use
   - No API key required
   - Limited rate limit info

4. **Custom Adapters**
   - Extend `TikTokAPIAdapter` base class
   - Add via `manager.add_custom_adapter()`

### Rate Limit Handling

- **Threshold**: Adapters disabled when ≤5 requests remaining
- **Reset Detection**: Automatically re-enables when limits reset
- **Temporary Disable**: Server errors disable adapters for 15-60 minutes

## Monitoring

### Real-time Status

```python
status = tiktok_service.get_adapters_status()
print(f"Available: {status['available_adapters']}/{status['total_adapters']}")

for adapter in status['adapters']:
    print(f"{adapter['name']}: {'✅' if adapter['available'] else '❌'}")
    if adapter['rate_limit_info']:
        rl = adapter['rate_limit_info']
        print(f"  Rate limit: {rl['remaining']}/{rl['limit']}")
```

### Logging

The system logs important events:

- Adapter failovers
- Rate limit hits
- API errors
- Configuration changes

## Best Practices

1. **Multiple API Keys**: Use 3-5 different RapidAPI keys for better resilience
2. **Mixed Providers**: Combine paid (RapidAPI) and free (TikWM) APIs
3. **Monitor Status**: Regularly check adapter status in production
4. **Error Handling**: Always check the `success` field in responses
5. **Rate Monitoring**: Watch rate limit consumption patterns

## Troubleshooting

### No Adapters Configured

```bash
# Check environment variables
python -c "from adapters.config import get_adapter_config_info; print(get_adapter_config_info())"
```

### All Adapters Failing

1. Check API keys are valid
2. Verify network connectivity
3. Check if TikTok URLs are valid format
4. Review logs for specific error messages

### Rate Limits Hit

- System automatically handles this
- Consider adding more API keys
- Monitor usage patterns
- Implement request queuing if needed

## Architecture

```
tiktok_service.py
├── TikTokAPIManager
│   ├── RapidAPIAdapter (multiple instances)
│   ├── TikWMAdapter
│   └── CustomAdapter (extensible)
├── Rate Limit Detection
├── Failover Logic
└── Status Monitoring
```

The adapter pattern makes it easy to add new TikTok API providers without changing existing code. Simply create a new adapter class and add it to the manager.