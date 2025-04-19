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

class DiscoveryResponse(BaseModel):
    """
    Model for discovery endpoint responses.
    All fields are optional to handle varied data sources.
    """
    task_id: str = Field(default="")
    title: str = Field(default="Untitled")
    video_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    view_count: int = Field(default=0)
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Allow additional fields in case of schema changes
    class Config:
        extra = "ignore"

@router.get("/trending")
async def get_trending_transcriptions(
    time_window: Optional[str] = "week",  # week, month, all
    category: Optional[str] = None,
    limit: int = 10
):
    """Get trending public transcriptions."""
    try:
        if supabase is None:
            logger.error("Cannot get trending: Supabase client not initialized")
            # Return empty list instead of error
            logger.info("Returning empty list due to missing Supabase client")
            return []

        logger.info(f"Fetching trending transcriptions: time_window={time_window}, category={category}, limit={limit}")
        
        try:
            # Build a simple query first to check schema
            response = await asyncio.to_thread(
                supabase.table('transcriptions')
                        .select('*')
                        .limit(1)
                        .execute
            )
            
            logger.info(f"Schema check response: {len(response.data) if response.data else 0} rows")
            
            # If we can't get any data, return empty list
            if not response.data:
                logger.info("No data found in transcriptions table, returning empty list")
                return []
                
            # Build the base query - removed visibility filter
            query = supabase.table('transcriptions') \
                        .select('*') \
                        .limit(limit)
                            
            # Add view_count ordering if the column exists in the sample data
            sample_row = response.data[0] if response.data else {}
            if 'view_count' in sample_row:
                query = query.order('view_count', desc=True)
                logger.info("Using view_count for ordering")
            else:
                query = query.order('created_at', desc=True)
                logger.info("Using created_at for ordering (view_count not found)")

            # Add category filter if specified and category exists in schema
            if category and 'category' in sample_row:
                query = query.eq('category', category)
                logger.info(f"Added category filter: {category}")

            # Add time window filter if created_at exists in schema
            if time_window != "all" and 'created_at' in sample_row:
                days = 7 if time_window == "week" else 30
                cutoff = datetime.now() - timedelta(days=days)
                query = query.gte('created_at', cutoff.isoformat())
                logger.info(f"Added time filter: >= {cutoff.isoformat()}")

            response = await asyncio.to_thread(query.execute)
            logger.info(f"Query returned {len(response.data) if response.data else 0} rows")
            
            # Process the response to match the model
            result = []
            for item in response.data:
                try:
                    # Check required fields exist and provide defaults if needed
                    entry = {
                        "task_id": item.get("task_id", ""),
                        "title": item.get("title", "Untitled"),
                        "video_id": item.get("video_id"),
                        "thumbnail_url": item.get("thumbnail_url"),
                        "view_count": item.get("view_count", 0),
                        "category": item.get("category"),
                        "tags": item.get("tags", []),
                        "created_at": item.get("created_at", datetime.now().isoformat())
                    }
                    result.append(entry)
                except Exception as e:
                    logger.warning(f"Skipping item due to error: {str(e)}")
                    
            return result
            
        except Exception as e:
            # If any error occurs with the query, log and return empty list
            logger.error(f"Error executing query: {str(e)}")
            return []
            
    except Exception as e:
        logger.error(f"Error getting trending transcriptions: {str(e)}", exc_info=True)
        # Return empty list instead of throwing an error
        return []

@router.get("/similar/{task_id}")
async def get_similar_transcriptions(
    task_id: str,
    limit: int = 5
):
    """Get similar transcriptions based on tags and category."""
    try:
        if supabase is None:
            logger.error(f"Cannot get similar transcriptions: Supabase client not initialized")
            # Return empty list instead of error
            return []

        # Try to get source transcription
        try:
            source = await asyncio.to_thread(
                supabase.table('transcriptions')
                        .select('tags, category')
                        .eq('task_id', task_id)
                        .single()
                        .execute
            )
            
            if not source.data:
                logger.warning(f"Source transcription not found: {task_id}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting source transcription: {str(e)}")
            return []

        # Build query for similar content - removed visibility filter
        try:
            query = supabase.table('transcriptions') \
                           .select('*') \
                           .neq('task_id', task_id)  # Exclude source

            # Add category and tag filters if available
            if source.data.get('category'):
                query = query.eq('category', source.data['category'])
                logger.info(f"Added category filter: {source.data['category']}")
            
            if source.data.get('tags') and isinstance(source.data['tags'], list) and len(source.data['tags']) > 0:
                # Try to add tags filter, but don't fail if not supported
                try:
                    query = query.contains('tags', source.data['tags'])
                    logger.info(f"Added tags filter: {source.data['tags']}")
                except Exception as e:
                    logger.warning(f"Failed to add tags filter: {str(e)}")

            # Try to order by view_count first, fall back to created_at
            try:
                query = query.order('view_count', desc=True)
                logger.info("Using view_count for ordering")
            except:
                query = query.order('created_at', desc=True)
                logger.info("Using created_at for ordering")
                    
            response = await asyncio.to_thread(
                query.limit(limit)
                     .execute
            )
            
            # Process the response to match the model
            result = []
            for item in response.data:
                try:
                    entry = {
                        "task_id": item.get("task_id", ""),
                        "title": item.get("title", "Untitled"),
                        "video_id": item.get("video_id"),
                        "thumbnail_url": item.get("thumbnail_url"),
                        "view_count": item.get("view_count", 0),
                        "category": item.get("category"),
                        "tags": item.get("tags", []),
                        "created_at": item.get("created_at", datetime.now().isoformat())
                    }
                    result.append(entry)
                except Exception as e:
                    logger.warning(f"Skipping item due to error: {str(e)}")
                    
            return result
            
        except Exception as e:
            logger.error(f"Error querying similar transcriptions: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error getting similar transcriptions: {str(e)}", exc_info=True)
        # Return empty list instead of error
        return []

@router.get("/recent")
async def get_recent_transcriptions(
    category: Optional[str] = None,
    limit: int = 10
):
    """Get recently added public transcriptions."""
    try:
        if supabase is None:
            logger.error("Cannot get recent: Supabase client not initialized")
            # Return empty list instead of error
            return []

        try:
            # Check schema first
            sample = await asyncio.to_thread(
                supabase.table('transcriptions')
                        .select('*')
                        .limit(1)
                        .execute
            )
            
            if not sample.data:
                logger.info("No data in transcriptions table, returning empty list")
                return []
                
            # Build query now that we know table exists
            query = supabase.table('transcriptions') \
                           .select('*') \
                           .order('created_at', desc=True) \
                           .limit(limit)

            # Add category filter if specified and column exists
            sample_row = sample.data[0] if sample.data else {}
            if category and 'category' in sample_row:
                query = query.eq('category', category)
                logger.info(f"Added category filter: {category}")

            response = await asyncio.to_thread(query.execute)
            logger.info(f"Recent query returned {len(response.data) if response.data else 0} rows")
            
            # Process the response to match the model
            result = []
            for item in response.data:
                try:
                    entry = {
                        "task_id": item.get("task_id", ""),
                        "title": item.get("title", "Untitled"),
                        "video_id": item.get("video_id"),
                        "thumbnail_url": item.get("thumbnail_url"),
                        "view_count": item.get("view_count", 0),
                        "category": item.get("category"),
                        "tags": item.get("tags", []),
                        "created_at": item.get("created_at", datetime.now().isoformat())
                    }
                    result.append(entry)
                except Exception as e:
                    logger.warning(f"Skipping item due to error: {str(e)}")
                    
            return result
            
        except Exception as e:
            logger.error(f"Error querying recent transcriptions: {str(e)}")
            return []

    except Exception as e:
        logger.error(f"Error getting recent transcriptions: {str(e)}", exc_info=True)
        # Return empty list instead of error
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
            supabase.table('transcriptions')
                    .select('category')
                    .execute
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