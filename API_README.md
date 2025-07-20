# API Documentation

**⚠️ DEPRECATED: This file is outdated. Please see [COMPLETE_API_DOCS.md](./COMPLETE_API_DOCS.md) for the most current and comprehensive API documentation.**

## Authentication

Most endpoints require API key authentication using the `X-API-Key` header.

```bash
curl -H "X-API-Key: your-api-key-here" https://your-api-url/endpoint
```

## Endpoints

### Task Management

#### Submit a Task
- **URL**: `/api/tasks`
- **Method**: `POST`
- **Auth Required**: Yes (`X-API-Key` header)
- **Data Example**:
```json
{
  "url": "https://www.tiktok.com/@user/video/123456789",
  "callback_url": null,
  "proxy": null
}
```
- **Success Response**: `{"task_id": "uuid-string"}`

#### Get Task Status
- **URL**: `/api/public/tasks/{task_id}`
- **Method**: `GET`
- **Auth Required**: No
- **Success Response**:
```json
{
  "task_id": "uuid-string",
  "status": "pending|processing|completed|failed",
  "video_id": "123456789",
  "title": "Video Title",
  "created_at": "2025-04-16T09:00:00",
  "error": null,
  "thumbnail": null,
  "thumbnail_url": null,
  "thumbnail_local_path": null
}
```

### Discovery

#### Get Trending Transcriptions
- **URL**: `/api/public/discover/trending`
- **Method**: `GET`
- **Auth Required**: No
- **Query Parameters**:
  - `time_window`: week|month|all (default: week)
  - `category`: string (optional)
  - `limit`: integer (default: 10)
- **Success Response**: Array of transcription objects

#### Get Similar Transcriptions
- **URL**: `/api/public/discover/similar/{task_id}`
- **Method**: `GET`
- **Auth Required**: No
- **Query Parameters**:
  - `limit`: integer (default: 5)
- **Success Response**: Array of transcription objects

#### Get Recent Transcriptions
- **URL**: `/api/public/discover/recent`
- **Method**: `GET`
- **Auth Required**: No
- **Query Parameters**:
  - `category`: string (optional)
  - `limit`: integer (default: 10)
- **Success Response**: Array of transcription objects

#### Get Categories
- **URL**: `/api/public/discover/categories`
- **Method**: `GET`
- **Auth Required**: No
- **Success Response**: Array of category strings

## Response Models

### Transcription Object
```json
{
  "task_id": "uuid-string",
  "title": "Video Title",
  "video_id": "123456789",
  "thumbnail_url": "https://...",
  "view_count": 0,
  "category": "entertainment",
  "tags": ["funny", "viral"],
  "created_at": "2025-04-16T09:00:00"
}
```

## Error Handling

Most endpoints now return empty arrays or default values instead of errors when possible.
When errors do occur, they will follow this format:

```json
{
  "detail": "Error message"
}
```

## Notes

- The Discovery endpoints are designed to be robust against database schema variations
- Empty result sets are returned as empty arrays `[]` rather than errors
- Default categories are provided when none exist in the database 