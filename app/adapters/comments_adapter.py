"""
TikTok Comments Adapter - Pro Feature
Fetches comments and replies from TikTok videos using multiple API providers.
"""

import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)


@dataclass
class Comment:
    """Normalized comment structure across all providers"""
    comment_id: str
    text: str
    author_name: str
    author_username: str
    author_avatar: Optional[str]
    created_at: str
    likes: int
    reply_count: int
    parent_comment_id: Optional[str] = None
    video_id: Optional[str] = None
    raw_data: Optional[Dict] = None


class TikTokCommentsAdapter:
    """
    Multi-provider comments adapter with automatic fallback.
    Supports: tiktok-api23, tiktok-download-video1, tiktok-scraper2
    """
    
    def __init__(self, api_keys: List[str]):
        """
        Initialize with list of RapidAPI keys.
        Keys will be tried in rotation for rate limit management.
        """
        self.api_keys = api_keys if isinstance(api_keys, list) else [api_keys]
        self.current_key_index = 0
        
        # Provider configurations
        self.providers = [
            {
                'name': 'tiktok-api23',
                'host': 'tiktok-api23.p.rapidapi.com',
                'endpoint': '/api/post/comments',
                'replies_endpoint': '/api/post/comment/replies',
                'parser': self._parse_api23
            },
            {
                'name': 'tiktok-download-video1', 
                'host': 'tiktok-download-video1.p.rapidapi.com',
                'endpoint': '/commentList',
                'replies_endpoint': '/commentReply',
                'parser': self._parse_downloadvideo1
            },
            {
                'name': 'tiktok-scraper2',
                'host': 'tiktok-scraper2.p.rapidapi.com',
                'endpoint': '/video/comments',
                'replies_endpoint': None,  # No dedicated replies endpoint
                'parser': self._parse_scraper2
            }
        ]
    
    def get_api_key(self) -> str:
        """Get current API key with rotation"""
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key
    
    def fetch_comments(
        self, 
        video_id: str, 
        count: int = 30,
        cursor: str = None,
        max_retries: int = 3,
        get_all: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch comments for a video with automatic provider fallback.
        
        Args:
            video_id: TikTok video ID
            count: Number of comments per page (ignored if get_all=True)
            cursor: Pagination cursor (ignored if get_all=True)
            max_retries: Maximum retry attempts per provider
            get_all: If True, fetch ALL comments with pagination
        
        Returns:
            {
                'comments': List[Comment],
                'cursor': str,
                'has_more': bool,
                'provider': str,
                'error': Optional[str],
                'pages_fetched': int (if get_all=True)
            }
        """
        if get_all:
            return self._fetch_all_comments_with_pagination(video_id, max_retries)
        else:
            return self._fetch_single_page(video_id, count, cursor, max_retries)
    
    def _fetch_single_page(
        self, 
        video_id: str, 
        count: int = 30,
        cursor: str = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch a single page of comments (original behavior)"""
        for provider in self.providers:
            for attempt in range(max_retries):
                try:
                    result = self._fetch_from_provider(
                        provider, video_id, count, cursor, max_retries
                    )
                    if result.get('comments'):
                        logger.info(
                            f"Successfully fetched {len(result['comments'])} comments "
                            f"from {provider['name']} for video {video_id}"
                        )
                        return result
                except Exception as e:
                    logger.warning(
                        f"Provider {provider['name']} attempt {attempt + 1} failed: {e}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(1)  # Brief delay before retry
                    continue
        
        # All providers failed
        logger.error(f"All comment providers failed for video {video_id}")
        return {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'All providers failed'
        }
    
    def _fetch_all_comments_with_pagination(
        self, 
        video_id: str, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch ALL comments using pagination with retry logic"""
        logger.info(f"Starting pagination fetch for video {video_id}")
        
        for provider in self.providers:
            try:
                logger.info(f"Trying provider: {provider['name']}")
                result = self._fetch_all_from_provider(provider, video_id, max_retries)
                if result.get('comments'):
                    logger.info(
                        f"Successfully fetched {len(result['comments'])} comments "
                        f"across {result.get('pages_fetched', 1)} pages "
                        f"from {provider['name']} for video {video_id}"
                    )
                    return result
            except Exception as e:
                logger.warning(f"Provider {provider['name']} failed: {e}")
                continue
        
        # All providers failed
        logger.error(f"All comment providers failed for video {video_id}")
        return {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'All providers failed',
            'pages_fetched': 0
        }
    
    def _fetch_all_from_provider(
        self, 
        provider: Dict, 
        video_id: str, 
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch all comments from a specific provider with pagination"""
        all_comments = []
        cursor = 0
        page_count = 0
        max_pages = 100  # Safety limit to prevent infinite loops
        
        while page_count < max_pages:
            logger.info(f"Fetching page {page_count + 1} with cursor {cursor}")
            
            # Retry logic for each page
            page_success = False
            for attempt in range(max_retries):
                try:
                    result = self._fetch_from_provider(provider, video_id, 50, cursor, max_retries)
                    
                    if result.get('comments'):
                        page_comments = result['comments']
                        all_comments.extend(page_comments)
                        page_count += 1
                        page_success = True
                        
                        logger.info(
                            f"Page {page_count}: Got {len(page_comments)} comments "
                            f"(total: {len(all_comments)})"
                        )
                        
                        # Check if there are more comments
                        has_more = self._has_more_comments(result.get('data', {}), provider['name'])
                        if not has_more:
                            logger.info("No more comments available")
                            break
                        
                        # Update cursor for next page
                        cursor = self._get_next_cursor(result.get('data', {}), provider['name'], cursor)
                        if cursor is None:
                            logger.info("No next cursor available")
                            break
                        
                        # Rate limiting between pages
                        time.sleep(1)  # 1 second delay between pages
                        break
                    else:
                        logger.warning(f"Page {page_count + 1}: No comments returned")
                        break
                        
                except Exception as e:
                    logger.warning(f"Page {page_count + 1} attempt {attempt + 1} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        logger.error(f"Page {page_count + 1} failed after {max_retries} attempts")
                        break
            
            if not page_success:
                logger.warning(f"Failed to fetch page {page_count + 1}, stopping pagination")
                break
        
        return {
            'comments': all_comments,
            'count': len(all_comments),
            'provider': provider['name'],
            'pages_fetched': page_count,
            'error': None
        }
    
    def fetch_comment_replies(
        self,
        video_id: str,
        comment_id: str,
        count: int = 20,
        cursor: str = None
    ) -> Dict[str, Any]:
        """Fetch replies to a specific comment"""
        for provider in self.providers:
            if not provider['replies_endpoint']:
                continue  # Skip providers without reply support
            
            try:
                api_key = self.get_api_key()
                headers = {
                    'X-RapidAPI-Key': api_key,
                    'X-RapidAPI-Host': provider['host']
                }
                
                base_url = f"https://{provider['host']}{provider['replies_endpoint']}"
                
                # Build params based on provider
                if provider['name'] == 'tiktok-api23':
                    params = {
                        'videoId': video_id,
                        'commentId': comment_id,
                        'count': count
                    }
                elif provider['name'] == 'tiktok-download-video1':
                    params = {
                        'comment_id': comment_id,
                        'video_id': video_id,
                        'count': count
                    }
                else:
                    continue
                
                if cursor:
                    params['cursor'] = cursor
                
                response = requests.get(base_url, headers=headers, params=params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    comments = provider['parser'](data, parent_id=comment_id)
                    
                    return {
                        'comments': comments,
                        'cursor': self._extract_cursor(data, provider['name']),
                        'has_more': self._extract_has_more(data, provider['name']),
                        'provider': provider['name'],
                        'error': None
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch replies from {provider['name']}: {e}")
                continue
        
        return {
            'comments': [],
            'cursor': None,
            'has_more': False,
            'provider': None,
            'error': 'No provider supports replies or all failed'
        }
    
    def _fetch_from_provider(
        self,
        provider: Dict,
        video_id: str,
        count: int,
        cursor: Optional[str],
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Fetch comments from a specific provider with enhanced error handling"""
        api_key = self.get_api_key()
        headers = {
            'X-RapidAPI-Key': api_key,
            'X-RapidAPI-Host': provider['host']
        }
        
        base_url = f"https://{provider['host']}{provider['endpoint']}"
        
        # Build params based on provider
        if provider['name'] == 'tiktok-api23':
            params = {'videoId': video_id, 'count': count}
        elif provider['name'] == 'tiktok-download-video1':
            # Needs full URL, but we have video_id - construct it
            params = {
                'url': f'https://www.tiktok.com/@x/video/{video_id}',
                'count': count
            }
        elif provider['name'] == 'tiktok-scraper2':
            params = {
                'video_url': f'https://www.tiktok.com/@x/video/{video_id}',
                'count': count
            }
        else:
            params = {'video_id': video_id, 'count': count}
        
        if cursor:
            params['cursor'] = cursor
        
        # Retry logic with exponential backoff
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, headers=headers, params=params, timeout=30)
                
                # Handle specific HTTP errors
                if response.status_code == 504:
                    logger.warning(f"Gateway timeout (504) on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Gateway timeout after {max_retries} attempts")
                
                if response.status_code == 429:
                    logger.warning(f"Rate limit (429) on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        time.sleep(10 * (attempt + 1))  # Longer delay for rate limits
                        continue
                    else:
                        raise requests.exceptions.RequestException(f"Rate limit exceeded after {max_retries} attempts")
                
                response.raise_for_status()
                data = response.json()
                comments = provider['parser'](data)
                
                return {
                    'comments': comments,
                    'cursor': self._extract_cursor(data, provider['name']),
                    'has_more': self._extract_has_more(data, provider['name']),
                    'provider': provider['name'],
                    'error': None,
                    'data': data  # Include raw data for pagination helpers
                }
                
            except requests.exceptions.Timeout:
                logger.warning(f"Request timeout on attempt {attempt + 1}, retrying...")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error on attempt {attempt + 1}, retrying...")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Request error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
            except Exception as e:
                logger.error(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5 * (attempt + 1))
                    continue
                else:
                    raise
        
        # This should never be reached due to the raise statements above
        raise Exception(f"Failed to fetch comments after {max_retries} attempts")
    
    def _parse_api23(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-api23 response format"""
        comments = []
        
        # Handle both direct comments array and nested data structure
        comments_data = data.get('comments', [])
        if not comments_data and 'data' in data:
            comments_data = data['data'].get('comments', [])
        
        for item in comments_data:
            try:
                user = item.get('user', {})
                comments.append(Comment(
                    comment_id=str(item.get('cid', '')),
                    text=item.get('text', ''),
                    author_name=user.get('nickname', 'Unknown'),
                    author_username=user.get('unique_id', ''),
                    author_avatar=user.get('avatar_thumb', {}).get('url_list', [None])[0],
                    created_at=str(item.get('create_time', '')),
                    likes=item.get('digg_count', 0),
                    reply_count=item.get('reply_comment_total', 0),
                    parent_comment_id=parent_id,
                    video_id=str(item.get('aweme_id', '')),
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue
        
        return comments
    
    def _parse_downloadvideo1(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-download-video1 response format"""
        comments = []
        
        comments_data = data.get('data', {}).get('comments', [])
        
        for item in comments_data:
            try:
                user = item.get('user', {})
                comments.append(Comment(
                    comment_id=str(item.get('id', '')),
                    text=item.get('text', ''),
                    author_name=user.get('nickname', 'Unknown'),
                    author_username=user.get('unique_id', ''),
                    author_avatar=user.get('avatar', ''),
                    created_at=str(item.get('create_time', '')),
                    likes=item.get('digg_count', 0),
                    reply_count=item.get('reply_total', 0),
                    parent_comment_id=parent_id,
                    video_id=None,
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue
        
        return comments
    
    def _parse_scraper2(self, data: Dict, parent_id: Optional[str] = None) -> List[Comment]:
        """Parse tiktok-scraper2 response format"""
        comments = []
        
        comments_data = data.get('comments', [])
        
        for item in comments_data:
            try:
                user = item.get('user', {})
                comments.append(Comment(
                    comment_id=str(item.get('cid', '')),
                    text=item.get('text', ''),
                    author_name=user.get('nickname', 'Unknown'),
                    author_username=user.get('unique_id', ''),
                    author_avatar=user.get('avatar_larger', {}).get('url_list', [None])[0],
                    created_at=str(item.get('create_time', '')),
                    likes=item.get('digg_count', 0),
                    reply_count=item.get('reply_comment_total', 0),
                    parent_comment_id=parent_id,
                    video_id=str(item.get('aweme_id', '')),
                    raw_data=item
                ))
            except Exception as e:
                logger.warning(f"Failed to parse comment: {e}")
                continue
        
        return comments
    
    def _extract_cursor(self, data: Dict, provider_name: str) -> Optional[str]:
        """Extract pagination cursor from response"""
        if provider_name == 'tiktok-api23':
            return data.get('cursor') or data.get('data', {}).get('cursor')
        elif provider_name == 'tiktok-download-video1':
            return data.get('data', {}).get('cursor')
        elif provider_name == 'tiktok-scraper2':
            return data.get('cursor')
        return None
    
    def _extract_has_more(self, data: Dict, provider_name: str) -> bool:
        """Extract has_more flag from response"""
        if provider_name == 'tiktok-api23':
            return data.get('has_more', False) or data.get('data', {}).get('has_more', False)
        elif provider_name == 'tiktok-download-video1':
            return data.get('data', {}).get('has_more', False)
        elif provider_name == 'tiktok-scraper2':
            return data.get('has_more', False)
        return False
    
    def _has_more_comments(self, data: Dict, provider_name: str) -> bool:
        """Check if there are more comments available for pagination"""
        if provider_name == 'tiktok-api23':
            # For tiktok-api23, check if comments array is not empty and has expected length
            comments = data.get('comments', [])
            return comments is not None and len(comments) > 0
        elif provider_name == 'tiktok-download-video1':
            # Check for pagination indicators in the response
            return data.get('has_more', False) or data.get('next_cursor') is not None
        elif provider_name == 'tiktok-scraper2':
            # Check for pagination indicators
            return data.get('has_more', False) or data.get('next_cursor') is not None
        else:
            # Default: assume there are more if we got comments
            comments = data.get('comments', [])
            return comments is not None and len(comments) > 0
    
    def _get_next_cursor(self, data: Dict, provider_name: str, current_cursor: int) -> Optional[int]:
        """Get the next cursor value for pagination"""
        if provider_name == 'tiktok-api23':
            # For tiktok-api23, increment cursor by the number of comments we got
            comments = data.get('comments', [])
            if comments and len(comments) > 0:
                return current_cursor + len(comments)
            return None
        elif provider_name == 'tiktok-download-video1':
            # Use the next_cursor from response
            return data.get('next_cursor')
        elif provider_name == 'tiktok-scraper2':
            # Use the next_cursor from response
            return data.get('next_cursor')
        else:
            # Default: increment by count
            comments = data.get('comments', [])
            if comments and len(comments) > 0:
                return current_cursor + len(comments)
            return None

