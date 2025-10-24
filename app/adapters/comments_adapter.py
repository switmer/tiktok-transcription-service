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
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Fetch comments for a video with automatic provider fallback.
        
        Returns:
            {
                'comments': List[Comment],
                'cursor': str,
                'has_more': bool,
                'provider': str,
                'error': Optional[str]
            }
        """
        for provider in self.providers:
            for attempt in range(max_retries):
                try:
                    result = self._fetch_from_provider(
                        provider, video_id, count, cursor
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
        cursor: Optional[str]
    ) -> Dict[str, Any]:
        """Fetch comments from a specific provider"""
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
        
        response = requests.get(base_url, headers=headers, params=params, timeout=30)
        
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")
        
        data = response.json()
        comments = provider['parser'](data)
        
        return {
            'comments': comments,
            'cursor': self._extract_cursor(data, provider['name']),
            'has_more': self._extract_has_more(data, provider['name']),
            'provider': provider['name'],
            'error': None
        }
    
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

