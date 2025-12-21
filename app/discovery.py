from typing import List, Optional, Any, Dict
from fastapi import APIRouter, HTTPException
import asyncio
from datetime import datetime, timedelta
import logging
from pydantic import BaseModel, Field

# Import supabase client - handle both package and direct imports
try:
    from .database import supabase
except ImportError:
    from database import supabase

# Initialize logger
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/public/discover", tags=["discovery"])

class AuthorInfo(BaseModel):
    nickname: str = Field(..., example="SteveHenny")
    unique_id: str = Field(..., example="step_henny0")

class DiscoveryResponse(BaseModel):
    task_id: str = Field(default="", example="550e8400-e29b-41d4-a716-446655440000")
    title: str = Field(default="Untitled", example="Comedy Skit - Banana Phone")
    video_id: Optional[str] = Field(None, example="7526401258786245902")
    thumbnail_url: Optional[str] = Field(None, example="https://cdn.tiktok.com/thumb.jpg")
    view_count: int = Field(default=0, example=94403)
    like_count: Optional[int] = Field(None, example=7230)
    comment_count: Optional[int] = Field(None, example=183)
    share_count: Optional[int] = Field(None, example=27)
    play_count: Optional[int] = Field(None, example=94403)
    duration: Optional[int] = Field(None, example=115)
    platform: Optional[str] = Field(None, example="tiktok")
    author: Optional[AuthorInfo] = None
    category: Optional[str] = Field(None, example="comedy")
    tags: Optional[List[str]] = Field(None, example=["funny", "viral"])
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(), example="2024-07-21T10:15:00Z")
    class Config:
        extra = "ignore"

class DiscoveryListResponse(BaseModel):
    tasks: List[DiscoveryResponse]

@router.get(
    "/trending",
    response_model=List[DiscoveryResponse],
    tags=["Content Discovery"],
    description="Get trending public transcriptions with full metadata for frontend rendering.",
)
async def get_trending_transcriptions(
    time_window: Optional[str] = "week",  # week, month, all
    category: Optional[str] = None,
    limit: int = 10
):
    """Get trending public transcriptions with full data for TranscriptionCard."""
    try:
        if supabase is None:
            logger.error("Cannot get trending: Supabase client not initialized")
            return []

        logger.info(f"Fetching trending transcriptions: time_window={time_window}, category={category}, limit={limit}")

        try:
            # Build query to get completed transcriptions with all fields
            query = supabase.table('transcriptions') \
                        .select('*') \
                        .eq('status', 'completed') \
                        .limit(limit)

            # Order by like_count (engagement) for trending, fallback to view_count, then created_at
            query = query.order('like_count', desc=True, nullsfirst=False)

            # Add category filter if specified
            if category:
                query = query.eq('category', category)
                logger.info(f"Added category filter: {category}")

            # Add time window filter
            if time_window != "all":
                days = 7 if time_window == "week" else 30
                cutoff = datetime.now() - timedelta(days=days)
                query = query.gte('created_at', cutoff.isoformat())
                logger.info(f"Added time filter: >= {cutoff.isoformat()}")

            response = await asyncio.to_thread(lambda: query.execute())
            logger.info(f"Trending query returned {len(response.data) if response.data else 0} rows")

            # Return full transcription data for frontend compatibility
            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error executing trending query: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error getting trending transcriptions: {str(e)}", exc_info=True)
        return []

@router.get("/similar/{task_id}", response_model=List[DiscoveryResponse])
async def get_similar_transcriptions(
    task_id: str,
    limit: int = 5
):
    """Get similar transcriptions with full data for TranscriptionCard."""
    try:
        if supabase is None:
            logger.error(f"Cannot get similar transcriptions: Supabase client not initialized")
            return []

        # Get source transcription to find category/tags
        try:
            source = await asyncio.to_thread(
                lambda: supabase.table('transcriptions')
                                .select('tags, category')
                                .eq('task_id', task_id)
                                .single()
                                .execute()
            )

            if not source.data:
                logger.warning(f"Source transcription not found: {task_id}")
                return []

        except Exception as e:
            logger.error(f"Error getting source transcription: {str(e)}")
            return []

        try:
            # Build query for similar completed content
            query = supabase.table('transcriptions') \
                           .select('*') \
                           .eq('status', 'completed') \
                           .neq('task_id', task_id) \
                           .order('like_count', desc=True, nullsfirst=False) \
                           .limit(limit)

            # Add category filter if available
            if source.data.get('category'):
                query = query.eq('category', source.data['category'])
                logger.info(f"Added category filter: {source.data['category']}")

            response = await asyncio.to_thread(query.execute)
            logger.info(f"Similar query returned {len(response.data) if response.data else 0} rows")

            # Return full transcription data for frontend compatibility
            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error querying similar transcriptions: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error getting similar transcriptions: {str(e)}", exc_info=True)
        return []

@router.get("/recent", response_model=List[DiscoveryResponse])
async def get_recent_transcriptions(
    category: Optional[str] = None,
    limit: int = 10
):
    """Get recently added public transcriptions with full data for TranscriptionCard."""
    try:
        if supabase is None:
            logger.error("Cannot get recent: Supabase client not initialized")
            return []

        logger.info(f"Fetching recent transcriptions: category={category}, limit={limit}")

        try:
            # Build query to get completed transcriptions with all fields
            query = supabase.table('transcriptions') \
                           .select('*') \
                           .eq('status', 'completed') \
                           .order('created_at', desc=True) \
                           .limit(limit)

            # Add category filter if specified
            if category:
                query = query.eq('category', category)
                logger.info(f"Added category filter: {category}")

            response = await asyncio.to_thread(lambda: query.execute())
            logger.info(f"Recent query returned {len(response.data) if response.data else 0} rows")

            # Return full transcription data for frontend compatibility
            return response.data if response.data else []

        except Exception as e:
            logger.error(f"Error querying recent transcriptions: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error getting recent transcriptions: {str(e)}", exc_info=True)
        return []

@router.get("/categories", response_model=List[str])
async def get_categories():
    """Get list of available categories."""
    try:
        if supabase is None:
            logger.error("Cannot get categories: Supabase client not initialized")
            raise HTTPException(status_code=500, detail="Database connection not available")

        # First, get the column names to confirm if 'category' and 'visibility' exist
        logger.info("Checking if columns exist in transcriptions table")
        
        # Try a simplified query that just gets any categories
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select('category')
                            .execute()
        )
        
        # Log the response for debugging
        logger.info(f"Categories query returned {len(response.data) if response.data else 0} rows")
        
        # Extract unique non-empty categories
        categories = set()
        for item in response.data:
            if item.get('category') and isinstance(item['category'], str):
                categories.add(item['category'])
        
        # If we have no categories, use a default list
        if not categories:
            default_categories = [
                "education", "entertainment", "music", "gaming", 
                "food", "fitness", "tech", "other"
            ]
            logger.info(f"No categories found in database, using defaults: {default_categories}")
            return default_categories
            
        # Return sorted list of categories
        sorted_categories = sorted(list(categories))
        logger.info(f"Returning {len(sorted_categories)} categories: {sorted_categories}")
        return sorted_categories

    except Exception as e:
        logger.error(f"Error getting categories: {str(e)}", exc_info=True)
        # Return default categories instead of failing
        default_categories = [
            "education", "entertainment", "music", "gaming", 
            "food", "fitness", "tech", "other"
        ]
        logger.info(f"Using default categories due to error: {default_categories}")
        return default_categories

class SearchResponse(BaseModel):
    task_id: str = Field(..., example="550e8400-e29b-41d4-a716-446655440000")
    title: str = Field(..., example="Motivational Speech About Success")
    quote: Optional[str] = Field(None, example="Success is not final, failure is not fatal")
    tldr: Optional[Any] = Field(None, example=["Key point 1", "Key point 2"])
    platform: Optional[str] = Field(None, example="tiktok")
    like_count: Optional[int] = Field(None, example=15420)
    view_count: Optional[int] = Field(None, example=94403)
    created_at: str = Field(..., example="2024-07-21T10:15:00Z")
    search_rank: float = Field(..., example=0.8567)

class SearchListResponse(BaseModel):
    query: str = Field(..., example="motivation success")
    results: List[SearchResponse]
    total_results: int = Field(..., example=42)

@router.get(
    "/search",
    response_model=SearchListResponse,
    tags=["Content Discovery"],
    description="Lightning-fast full-text search across transcript, quote, and TLDR content with relevance ranking."
)
async def search_content(
    q: str,  # Search query
    limit: int = 20,
    offset: int = 0
):
    """Search transcriptions using full-text search across all content."""
    try:
        if supabase is None:
            logger.error("Cannot search: Supabase client not initialized")
            return SearchListResponse(query=q, results=[], total_results=0)

        if not q or len(q.strip()) < 2:
            logger.warning("Search query too short")
            return SearchListResponse(query=q, results=[], total_results=0)

        logger.info(f"Performing FTS search: query='{q}', limit={limit}, offset={offset}")

        try:
            # Use the production FTS function
            response = await asyncio.to_thread(
                lambda: supabase.rpc('search_content', {
                    'search_query': q.strip(),
                    'limit_count': limit,
                    'offset_count': offset
                }).execute()
            )

            if not response.data:
                logger.info(f"No search results for query: {q}")
                return SearchListResponse(query=q, results=[], total_results=0)

            # Process results
            results = []
            for item in response.data:
                try:
                    result = SearchResponse(
                        task_id=item.get("task_id", ""),
                        title=item.get("title", "Untitled"),
                        quote=item.get("quote"),
                        tldr=item.get("tldr"),
                        platform=item.get("platform"),
                        like_count=item.get("like_count"),
                        view_count=item.get("view_count"),
                        created_at=item.get("created_at", datetime.now().isoformat()),
                        search_rank=float(item.get("search_rank", 0.0))
                    )
                    results.append(result)
                except Exception as e:
                    logger.warning(f"Skipping search result due to error: {str(e)}")

            logger.info(f"FTS search returned {len(results)} results for query: {q}")
            
            return SearchListResponse(
                query=q,
                results=results,
                total_results=len(results)  # Could be enhanced with actual count
            )

        except Exception as e:
            logger.error(f"Error executing FTS search: {str(e)}")
            return SearchListResponse(query=q, results=[], total_results=0)

    except Exception as e:
        logger.error(f"Error in search endpoint: {str(e)}", exc_info=True)
        return SearchListResponse(query=q, results=[], total_results=0)

@router.get(
    "/viral",
    response_model=List[SearchResponse],
    tags=["Content Discovery"],
    description="Search for viral quotes with high engagement and relevance ranking."
)
async def search_viral_content(
    q: str,  # Search query
    min_likes: int = 10,
    limit: int = 10
):
    """Search for viral quotes with high engagement."""
    try:
        if supabase is None:
            logger.error("Cannot search viral: Supabase client not initialized")
            return []

        if not q or len(q.strip()) < 2:
            logger.warning("Viral search query too short")
            return []

        logger.info(f"Performing viral search: query='{q}', min_likes={min_likes}, limit={limit}")

        try:
            # Use the viral quotes FTS function
            response = await asyncio.to_thread(
                supabase.rpc('search_viral_quotes', {
                    'search_query': q.strip(),
                    'min_likes': min_likes,
                    'limit_count': limit
                }).execute()
            )

            if not response.data:
                logger.info(f"No viral results for query: {q}")
                return []

            # Process results
            results = []
            for item in response.data:
                try:
                    result = SearchResponse(
                        task_id=item.get("task_id", ""),
                        title=item.get("title", "Untitled"),
                        quote=item.get("quote"),
                        tldr=None,  # Viral search focuses on quotes
                        platform=item.get("platform"),
                        like_count=item.get("like_count"),
                        view_count=None,
                        created_at=datetime.now().isoformat(),  # Not returned by viral function
                        search_rank=float(item.get("search_rank", 0.0))
                    )
                    results.append(result)
                except Exception as e:
                    logger.warning(f"Skipping viral result due to error: {str(e)}")

            logger.info(f"Viral search returned {len(results)} results for query: {q}")
            return results

        except Exception as e:
            logger.error(f"Error executing viral search: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error in viral search endpoint: {str(e)}", exc_info=True)
        return [] 
