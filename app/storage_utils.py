"""
Utility functions for Supabase Storage operations
"""
import os
import logging
from typing import Optional
from database import supabase

logger = logging.getLogger(__name__)

async def upload_thumbnail_to_supabase(local_file_path: str, task_id: str, video_id: str) -> Optional[str]:
    """
    Upload thumbnail to Supabase Storage and return public URL
    
    Args:
        local_file_path: Path to local thumbnail file
        task_id: Task ID for organization
        video_id: Video ID for filename
        
    Returns:
        Public URL of uploaded thumbnail or None if failed
    """
    if not supabase:
        logger.error("Supabase client not initialized")
        return None
        
    if not os.path.exists(local_file_path):
        logger.error(f"Local thumbnail file does not exist: {local_file_path}")
        return None
        
    try:
        bucket_name = "assets"
        # Use task_id/video_id structure for organization
        file_extension = os.path.splitext(local_file_path)[1] or '.jpg'
        storage_path = f"thumbnails/{task_id}/{video_id}{file_extension}"
        
        logger.info(f"Uploading thumbnail to Supabase Storage: {storage_path}")
        
        # Read file data
        with open(local_file_path, 'rb') as f:
            file_data = f.read()
            
        # Determine content type based on file extension
        content_type = 'image/jpeg'
        if file_extension.lower() in ['.png']:
            content_type = 'image/png'
        elif file_extension.lower() in ['.webp']:
            content_type = 'image/webp'
            
        # Upload to Supabase Storage
        response = supabase.storage.from_(bucket_name).upload(
            storage_path, 
            file_data,
            file_options={
                'content-type': content_type, 
                'cache-control': '3600',
                'upsert': True  # Allow overwriting if file exists
            }
        )
        
        # Check for upload errors
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase upload failed: {response.error}")
            return None
            
        # Get public URL
        public_url_response = supabase.storage.from_(bucket_name).get_public_url(storage_path)
        
        if hasattr(public_url_response, 'error') and public_url_response.error:
            logger.error(f"Failed to get public URL: {public_url_response.error}")
            return None
            
        # Extract URL from response
        public_url = public_url_response.get('publicURL') or public_url_response.get('data', {}).get('publicUrl') or str(public_url_response)
        
        logger.info(f"Successfully uploaded thumbnail to Supabase: {public_url}")
        return public_url
        
    except Exception as e:
        logger.error(f"Error uploading thumbnail to Supabase: {str(e)}", exc_info=True)
        return None


async def delete_thumbnail_from_supabase(storage_path: str) -> bool:
    """
    Delete thumbnail from Supabase Storage
    
    Args:
        storage_path: Path in storage (e.g., 'thumbnails/task_id/video_id.jpg')
        
    Returns:
        True if successful, False otherwise
    """
    if not supabase:
        logger.error("Supabase client not initialized")
        return False
        
    try:
        bucket_name = "assets"
        response = supabase.storage.from_(bucket_name).remove([storage_path])
        
        if hasattr(response, 'error') and response.error:
            logger.error(f"Failed to delete thumbnail from Supabase: {response.error}")
            return False
            
        logger.info(f"Successfully deleted thumbnail from Supabase: {storage_path}")
        return True
        
    except Exception as e:
        logger.error(f"Error deleting thumbnail from Supabase: {str(e)}", exc_info=True)
        return False


def extract_storage_path_from_url(supabase_url: str, bucket_name: str = "assets") -> Optional[str]:
    """
    Extract storage path from Supabase public URL
    
    Args:
        supabase_url: Full Supabase public URL
        bucket_name: Bucket name (default: "assets")
        
    Returns:
        Storage path or None if extraction fails
    """
    try:
        # Supabase URLs typically look like:
        # https://project.supabase.co/storage/v1/object/public/bucket/path/to/file
        if f"/storage/v1/object/public/{bucket_name}/" in supabase_url:
            return supabase_url.split(f"/storage/v1/object/public/{bucket_name}/")[1]
        return None
    except Exception as e:
        logger.error(f"Error extracting storage path from URL: {str(e)}")
        return None