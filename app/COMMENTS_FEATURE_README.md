# Comment Extraction Feature (Pro)

## Overview

The comment extraction feature allows users to fetch and store TikTok video comments alongside transcriptions. This is a **premium feature** that costs **1 credit per request**.

## Features

✅ **Multi-Provider Fallback**: Automatically tries multiple RapidAPI providers for reliability
✅ **Comment Storage**: Stores comments in database for fast retrieval
✅ **Sorting & Filtering**: Get comments by likes, recency, or reply count
✅ **Top Comments API**: Quick access to most-liked comments
✅ **Credit-Based Billing**: Fair usage pricing (1 credit per 30 comments)
✅ **Reply Threading**: Support for nested comment replies (where available)

## API Providers

The adapter uses these providers in order of preference:

1. **tiktok-api23** (Lundehund) - Best quality, full reply support
2. **tiktok-download-video1** (llbbmm) - Good fallback with URL support
3. **tiktok-scraper2** (JoTucker) - Lightweight option for top-level comments

## API Endpoints

### 1. Fetch Comments (Pro)

```http
POST /api/pro/comments/fetch
Content-Type: application/json
X-API-Key: your-api-key

{
  "task_id": "abc-123-def",
  "count": 30,
  "include_replies": false
}
```

**Response:**
```json
{
  "success": true,
  "task_id": "abc-123-def",
  "comments_fetched": 28,
  "provider": "tiktok-api23",
  "has_more": true,
  "cursor": "eyJhd2VtZV9pZCI6...=="
}
```

**Cost:** 1 credit per request

### 2. Get Stored Comments

```http
GET /api/public/comments/{task_id}?limit=50&offset=0&sort_by=likes
X-API-Key: your-api-key
```

**Sort Options:**
- `likes` - Most liked first (default)
- `recent` - Most recent first
- `replies` - Most replies first

**Response:**
```json
{
  "task_id": "abc-123-def",
  "comments": [
    {
      "id": "uuid",
      "comment_id": "7123456789",
      "text": "Amazing video! 🔥",
      "author_name": "John Doe",
      "author_username": "johndoe",
      "author_avatar": "https://...",
      "likes": 1250,
      "reply_count": 15,
      "created_at_timestamp": "1234567890",
      "fetched_at": "2025-10-23T14:00:00Z"
    }
  ],
  "count": 28,
  "offset": 0,
  "limit": 50
}
```

### 3. Get Top Comments

```http
GET /api/public/comments/{task_id}/top?limit=10
X-API-Key: your-api-key
```

Returns the top N most-liked comments (top-level only, no replies).

## Database Schema

### `video_comments` Table

```sql
CREATE TABLE video_comments (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES transcriptions(task_id),
    comment_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    text TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_username TEXT NOT NULL,
    author_avatar TEXT,
    created_at_timestamp TEXT,
    likes INTEGER DEFAULT 0,
    reply_count INTEGER DEFAULT 0,
    parent_comment_id TEXT,
    provider TEXT,
    raw_data JSONB,
    fetched_at TIMESTAMP,
    UNIQUE(task_id, comment_id)
);
```

### `transcriptions` Table Updates

Added columns:
- `comments_fetched` (BOOLEAN)
- `comments_count` (INTEGER)
- `comments_fetched_at` (TIMESTAMP)

## Usage Example (Python)

```python
import requests

API_KEY = "your-api-key"
BASE_URL = "https://share.scribetok.com"

# 1. Transcribe a video first
response = requests.post(
    f"{BASE_URL}/api/public/transcribe",
    headers={"X-API-Key": API_KEY},
    json={"url": "https://www.tiktok.com/@user/video/1234567890"}
)
task_id = response.json()["task_id"]

# Wait for transcription to complete...

# 2. Fetch comments (costs 1 credit)
response = requests.post(
    f"{BASE_URL}/api/pro/comments/fetch",
    headers={"X-API-Key": API_KEY},
    json={"task_id": task_id, "count": 30}
)

print(f"Fetched {response.json()['comments_fetched']} comments")

# 3. Get top comments
response = requests.get(
    f"{BASE_URL}/api/public/comments/{task_id}/top?limit=5",
    headers={"X-API-Key": API_KEY}
)

for comment in response.json()["top_comments"]:
    print(f"{comment['author_name']}: {comment['text']} ({comment['likes']} likes)")
```

## Configuration

### Environment Variables

```bash
# Required for comment extraction
RAPIDAPI_KEY=your_rapidapi_key

# Optional: Specific keys for comment providers
RAPIDAPI_COMMENTS_KEYS=key1,key2,key3
```

### Provider Selection

The adapter automatically selects the best available provider based on:
1. **Success rate**: Providers that consistently return data
2. **Rate limits**: Rotates through API keys
3. **Feature support**: Prefers providers with reply support

## Credit System Integration

Comment extraction integrates with the existing SMS credit system:

- **Cost**: 1 credit per request (covers up to 30 comments + replies)
- **Validation**: Checks user credits before fetching
- **Deduction**: Automatically deducts credit on success
- **Error Handling**: No credit charged if fetch fails

## Pricing Recommendations

Suggested pricing for end users:

- **Free Tier**: 3 credits/month (3 comment fetches)
- **Starter**: $5/month = 10 credits (10 fetches)
- **Pro**: $15/month = 50 credits (50 fetches)
- **Enterprise**: Custom pricing

## Error Handling

The adapter implements robust error handling:

1. **Provider Fallback**: Tries all 3 providers before failing
2. **Retry Logic**: 3 retry attempts per provider
3. **Graceful Degradation**: Returns partial results on rate limits
4. **Credit Safety**: Only charges on successful fetch

## Common Issues

### "All providers failed"
- Check RapidAPI subscription status
- Verify API key is valid
- Check rate limits on RapidAPI dashboard

### "Insufficient credits"
- User needs to purchase more credits
- Check `sms_users.credits_remaining`

### "Video ID not available"
- Only works for videos transcribed via RapidAPI
- Older transcriptions may not have video_id

## Future Enhancements

Potential improvements:

- [ ] Sentiment analysis on comments
- [ ] Comment moderation/filtering
- [ ] Real-time comment streaming
- [ ] Comment reply fetching UI
- [ ] Export comments to CSV/JSON
- [ ] Comment search functionality
- [ ] Author profile enrichment
- [ ] Trending comment detection

## Testing

```bash
# Test comment fetch
curl -X POST https://share.scribetok.com/api/pro/comments/fetch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"task_id": "your-task-id", "count": 10}'

# Test comment retrieval
curl https://share.scribetok.com/api/public/comments/your-task-id/top?limit=5 \
  -H "X-API-Key: your-key"
```

## Migration

To enable this feature in production:

```bash
# 1. Apply database migration
supabase db push

# 2. Deploy backend with new endpoints
git add .
git commit -m "Add comment extraction feature (Pro)"
git push

# 3. Configure RapidAPI keys
# Set RAPIDAPI_KEY in Render environment variables
```

## Support

For issues or questions:
- Check RapidAPI provider status
- Review Render logs for error details
- Verify database migrations applied correctly
- Test with a single comment fetch first

