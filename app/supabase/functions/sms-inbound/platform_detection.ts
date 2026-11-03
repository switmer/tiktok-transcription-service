/**
 * Platform detection utilities for ScribeTok SMS inbound.
 * This module handles URL cleaning, platform detection, and validation.
 * 
 * Supported platforms:
 * - TikTok: tiktok.com, vm.tiktok.com
 * - YouTube: youtube.com, youtu.be, m.youtube.com (watch, shorts, live, embed)
 * - Instagram: instagram.com, instagr.am (reels, reel, p, tv, with/without username)
 * - Facebook: facebook.com, fb.watch, fb.gg
 * - X/Twitter: x.com, twitter.com (status URLs)
 * - Reddit: reddit.com, redd.it, v.redd.it
 * - Vimeo: vimeo.com, player.vimeo.com
 * - Twitch: twitch.tv, clips.twitch.tv
 * - LinkedIn: linkedin.com (posts with video)
 * - Threads: threads.net
 * - Loom: loom.com
 * - Spotify: open.spotify.com/episode
 */

export type Platform = 
  | 'tiktok'
  | 'youtube'
  | 'instagram'
  | 'facebook'
  | 'twitter'  // X/Twitter stored as 'twitter' in DB
  | 'reddit'
  | 'vimeo'
  | 'twitch'
  | 'linkedin'
  | 'threads'
  | 'loom'
  | 'spotify'
  | null;

/**
 * Clean trailing punctuation from URLs that may be added by users or SMS clients.
 * Common patterns: URL followed by ) . , ! ? ; :
 */
export function cleanUrlTrailingPunctuation(url: string): string {
  if (!url) return url;
  // Remove trailing punctuation that is unlikely to be part of a valid URL
  // Be careful not to remove query string parts
  return url.replace(/[).\,!?;:]+$/, '');
}

/**
 * Check if URL is a TikTok video URL.
 * Patterns:
 * - https://www.tiktok.com/@username/video/1234567890
 * - https://tiktok.com/@username/video/1234567890
 * - https://vm.tiktok.com/XXXXXXX/
 * - https://tiktok.com/t/XXXXXXX/
 */
export function isTikTokUrl(url: string): boolean {
  return /(?:tiktok\.com\/@[^/]+\/video\/|tiktok\.com\/t\/|vm\.tiktok\.com\/)/i.test(url);
}

/**
 * Check if URL is a YouTube video URL.
 * Patterns:
 * - https://www.youtube.com/watch?v=XXXXXXXXXXX
 * - https://youtube.com/watch?v=XXXXXXXXXXX&other_param=value
 * - https://youtu.be/XXXXXXXXXXX
 * - https://www.youtube.com/shorts/XXXXXXXXXXX
 * - https://youtube.com/live/XXXXXXXXXXX
 * - https://www.youtube.com/embed/XXXXXXXXXXX
 * - https://m.youtube.com/watch?v=XXXXXXXXXXX
 * - https://music.youtube.com/watch?v=XXXXXXXXXXX
 * - v= can appear anywhere in query string (not just first)
 */
export function isYouTubeUrl(url: string): boolean {
  // Check for standard patterns
  if (/(?:youtube\.com\/(?:watch|shorts|live|embed)|youtu\.be\/)/i.test(url)) {
    return true;
  }
  // Check for v= anywhere in youtube.com URL query string
  if (/youtube\.com.*[?&]v=[\w-]{11}/i.test(url)) {
    return true;
  }
  // Check for m.youtube.com or music.youtube.com
  if (/(?:m\.youtube\.com|music\.youtube\.com)\/watch/i.test(url)) {
    return true;
  }
  return false;
}

/**
 * Check if URL is an Instagram video URL.
 * Patterns:
 * - https://www.instagram.com/reel/XXXXXXXXXXX/
 * - https://instagram.com/reels/XXXXXXXXXXX/
 * - https://www.instagram.com/p/XXXXXXXXXXX/
 * - https://www.instagram.com/tv/XXXXXXXXXXX/
 * - https://www.instagram.com/username/reel/XXXXXXXXXXX/
 * - https://www.instagram.com/username/p/XXXXXXXXXXX/
 * - https://instagr.am/p/XXXXXXXXXXX/
 * - https://www.instagram.com/share/reel/XXXXXXXXXXX/
 * - Instagram share links with ?igsh= tracking
 */
export function isInstagramUrl(url: string): boolean {
  // Match instagr.am short URLs
  if (/instagr\.am\//i.test(url)) {
    return true;
  }
  // Match instagram.com with various path patterns
  // Direct: /reel/, /reels/, /p/, /tv/
  // Username-prefixed: /@username/reel/, /username/reel/
  // Share links: /share/reel/
  if (/instagram\.com\/(?:(?:reel|reels|p|tv)\/|[^/]+\/(?:reel|reels|p|tv)\/|share\/(?:reel|p|video)\/)/i.test(url)) {
    return true;
  }
  return false;
}

/**
 * Check if URL is a Facebook video URL.
 * Patterns:
 * - https://www.facebook.com/username/videos/1234567890
 * - https://www.facebook.com/watch?v=1234567890
 * - https://www.facebook.com/reel/1234567890
 * - https://fb.watch/XXXXXXX/
 * - https://fb.gg/v/XXXXXXX/
 */
export function isFacebookUrl(url: string): boolean {
  return /(?:facebook\.com\/(?:.*\/videos\/|watch\?v=|reel\/)|fb\.watch\/|fb\.gg\/v\/)/i.test(url);
}

/**
 * Check if URL is an X/Twitter status URL.
 * Patterns:
 * - https://x.com/username/status/1234567890
 * - https://twitter.com/username/status/1234567890
 * - https://www.twitter.com/username/status/1234567890
 * - https://mobile.twitter.com/username/status/1234567890
 */
export function isXTwitterUrl(url: string): boolean {
  return /(?:x\.com|(?:www\.|mobile\.)?twitter\.com)\/[^/]+\/status\/\d+/i.test(url);
}

/**
 * Check if URL is a Reddit video URL.
 * Patterns:
 * - https://www.reddit.com/r/subreddit/comments/xxxxx/title/
 * - https://reddit.com/r/subreddit/comments/xxxxx/
 * - https://redd.it/xxxxx
 * - https://v.redd.it/xxxxx
 * - https://www.reddit.com/r/subreddit/s/xxxxx (share links)
 */
export function isRedditUrl(url: string): boolean {
  return /(?:reddit\.com\/r\/[^/]+\/(?:comments|s)\/|redd\.it\/|v\.redd\.it\/)/i.test(url);
}

/**
 * Check if URL is a Vimeo video URL.
 * Patterns:
 * - https://vimeo.com/1234567890
 * - https://player.vimeo.com/video/1234567890
 * - https://vimeo.com/channels/xxxxx/1234567890
 * - https://vimeo.com/groups/xxxxx/videos/1234567890
 */
export function isVimeoUrl(url: string): boolean {
  return /(?:vimeo\.com\/(?:\d+|channels\/[^/]+\/\d+|groups\/[^/]+\/videos\/\d+)|player\.vimeo\.com\/video\/\d+)/i.test(url);
}

/**
 * Check if URL is a Twitch clip or VOD URL.
 * Patterns:
 * - https://clips.twitch.tv/ClipName
 * - https://www.twitch.tv/username/clip/ClipName
 * - https://www.twitch.tv/videos/1234567890
 */
export function isTwitchUrl(url: string): boolean {
  return /(?:clips\.twitch\.tv\/|twitch\.tv\/(?:[^/]+\/clip\/|videos\/))/i.test(url);
}

/**
 * Check if URL is a LinkedIn post URL (may contain video).
 * Patterns:
 * - https://www.linkedin.com/posts/username_xxxxx
 * - https://www.linkedin.com/feed/update/urn:li:activity:xxxxx
 * - https://www.linkedin.com/video/...
 */
export function isLinkedInUrl(url: string): boolean {
  return /linkedin\.com\/(?:posts\/|feed\/update\/|video\/)/i.test(url);
}

/**
 * Check if URL is a Threads post URL.
 * Patterns:
 * - https://www.threads.net/@username/post/xxxxx
 * - https://threads.net/@username/post/xxxxx
 */
export function isThreadsUrl(url: string): boolean {
  return /threads\.net\/@[^/]+\/post\//i.test(url);
}

/**
 * Check if URL is a Loom video URL.
 * Patterns:
 * - https://www.loom.com/share/xxxxx
 * - https://loom.com/share/xxxxx
 */
export function isLoomUrl(url: string): boolean {
  return /loom\.com\/share\//i.test(url);
}

/**
 * Check if URL is a Spotify podcast episode URL.
 * Patterns:
 * - https://open.spotify.com/episode/xxxxx
 */
export function isSpotifyUrl(url: string): boolean {
  return /open\.spotify\.com\/episode\//i.test(url);
}

/**
 * Detect the platform from a URL.
 * Returns null if the URL is not from a supported platform.
 */
export function detectPlatform(url: string): Platform {
  if (!url) return null;
  
  // Clean trailing punctuation first
  const cleanUrl = cleanUrlTrailingPunctuation(url);
  
  if (isTikTokUrl(cleanUrl)) return 'tiktok';
  if (isYouTubeUrl(cleanUrl)) return 'youtube';
  if (isInstagramUrl(cleanUrl)) return 'instagram';
  if (isFacebookUrl(cleanUrl)) return 'facebook';
  if (isXTwitterUrl(cleanUrl)) return 'twitter';
  if (isRedditUrl(cleanUrl)) return 'reddit';
  if (isVimeoUrl(cleanUrl)) return 'vimeo';
  if (isTwitchUrl(cleanUrl)) return 'twitch';
  if (isLinkedInUrl(cleanUrl)) return 'linkedin';
  if (isThreadsUrl(cleanUrl)) return 'threads';
  if (isLoomUrl(cleanUrl)) return 'loom';
  if (isSpotifyUrl(cleanUrl)) return 'spotify';
  
  return null;
}

/**
 * Check if a URL is from any supported platform.
 */
export function isSupportedUrl(url: string): boolean {
  return detectPlatform(url) !== null;
}

/**
 * Extract YouTube video ID from URL.
 * Handles watch?v=, youtu.be/, shorts/, live/, embed/ formats.
 * v= can appear anywhere in query string.
 */
export function extractYouTubeVideoId(url: string): string | null {
  // Handle youtu.be short URLs
  let match = url.match(/youtu\.be\/([\w-]{11})/);
  if (match) return match[1];
  
  // Handle shorts, live, embed URLs
  match = url.match(/youtube\.com\/(?:shorts|live|embed)\/([\w-]{11})/);
  if (match) return match[1];
  
  // Handle v= anywhere in query string
  match = url.match(/[?&]v=([\w-]{11})/);
  if (match) return match[1];
  
  return null;
}

/**
 * Get a human-readable list of supported platforms.
 */
export function getSupportedPlatformsList(): string {
  return 'TikTok, YouTube, Instagram, Facebook, X/Twitter, Reddit, Vimeo, Twitch, LinkedIn, Threads, Loom, and Spotify podcasts';
}

/**
 * Get the message to send when a URL is not supported.
 */
export function getUnsupportedUrlMessage(): string {
  return `⚠️ We support ${getSupportedPlatformsList()}. Send a link from one of those platforms and I'll transcribe it!`;
}
