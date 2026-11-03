/**
 * Platform Detection Tests for Edge Function
 * 
 * Run with: deno test --allow-read platform_detection_test.ts
 */
import { assertEquals, assertNotEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import {
  cleanUrlTrailingPunctuation,
  detectPlatform,
  isTikTokUrl,
  isYouTubeUrl,
  isInstagramUrl,
  isFacebookUrl,
  isXTwitterUrl,
  isRedditUrl,
  isVimeoUrl,
  isTwitchUrl,
  isLinkedInUrl,
  isThreadsUrl,
  isLoomUrl,
  isSpotifyUrl,
  extractYouTubeVideoId,
  isSupportedUrl,
  type Platform,
} from "./platform_detection.ts";

// Trailing punctuation tests
Deno.test("cleanUrlTrailingPunctuation - removes trailing period", () => {
  assertEquals(
    cleanUrlTrailingPunctuation("https://tiktok.com/@user/video/123."),
    "https://tiktok.com/@user/video/123"
  );
});

Deno.test("cleanUrlTrailingPunctuation - removes trailing parenthesis", () => {
  assertEquals(
    cleanUrlTrailingPunctuation("https://youtu.be/abc123)"),
    "https://youtu.be/abc123"
  );
});

Deno.test("cleanUrlTrailingPunctuation - removes multiple punctuation", () => {
  assertEquals(
    cleanUrlTrailingPunctuation("https://x.com/user/status/123...)"),
    "https://x.com/user/status/123"
  );
});

Deno.test("cleanUrlTrailingPunctuation - preserves query strings", () => {
  assertEquals(
    cleanUrlTrailingPunctuation("https://youtube.com/watch?v=abc123"),
    "https://youtube.com/watch?v=abc123"
  );
});

// TikTok tests
Deno.test("isTikTokUrl - standard video URL", () => {
  assertEquals(isTikTokUrl("https://www.tiktok.com/@user/video/123456789"), true);
});

Deno.test("isTikTokUrl - vm.tiktok short URL", () => {
  assertEquals(isTikTokUrl("https://vm.tiktok.com/ZMxxxxx/"), true);
});

Deno.test("isTikTokUrl - t shortlink", () => {
  assertEquals(isTikTokUrl("https://tiktok.com/t/ZSxxxxx/"), true);
});

// YouTube tests
Deno.test("isYouTubeUrl - standard watch URL", () => {
  assertEquals(isYouTubeUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), true);
});

Deno.test("isYouTubeUrl - youtu.be short URL", () => {
  assertEquals(isYouTubeUrl("https://youtu.be/dQw4w9WgXcQ"), true);
});

Deno.test("isYouTubeUrl - shorts URL", () => {
  assertEquals(isYouTubeUrl("https://youtube.com/shorts/abcdefghijk"), true);
});

Deno.test("isYouTubeUrl - v= not first param", () => {
  assertEquals(isYouTubeUrl("https://youtube.com/watch?list=PLxxx&v=abc12345678"), true);
});

Deno.test("isYouTubeUrl - mobile URL", () => {
  assertEquals(isYouTubeUrl("https://m.youtube.com/watch?v=abc12345678"), true);
});

Deno.test("isYouTubeUrl - music URL", () => {
  assertEquals(isYouTubeUrl("https://music.youtube.com/watch?v=abc12345678"), true);
});

Deno.test("isYouTubeUrl - live URL", () => {
  assertEquals(isYouTubeUrl("https://youtube.com/live/abcdefghijk"), true);
});

Deno.test("isYouTubeUrl - embed URL", () => {
  assertEquals(isYouTubeUrl("https://youtube.com/embed/abcdefghijk"), true);
});

Deno.test("extractYouTubeVideoId - watch URL", () => {
  assertEquals(extractYouTubeVideoId("https://youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ");
});

Deno.test("extractYouTubeVideoId - youtu.be URL", () => {
  assertEquals(extractYouTubeVideoId("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ");
});

Deno.test("extractYouTubeVideoId - shorts URL", () => {
  assertEquals(extractYouTubeVideoId("https://youtube.com/shorts/abcdefghijk"), "abcdefghijk");
});

// Instagram tests
Deno.test("isInstagramUrl - reel URL", () => {
  assertEquals(isInstagramUrl("https://www.instagram.com/reel/Cxxxxxxxxxx/"), true);
});

Deno.test("isInstagramUrl - reels URL", () => {
  assertEquals(isInstagramUrl("https://instagram.com/reels/Cxxxxxxxxxx/"), true);
});

Deno.test("isInstagramUrl - post URL", () => {
  assertEquals(isInstagramUrl("https://instagram.com/p/ABC123/"), true);
});

Deno.test("isInstagramUrl - tv URL", () => {
  assertEquals(isInstagramUrl("https://www.instagram.com/tv/Cxxxxxxxxxx/"), true);
});

Deno.test("isInstagramUrl - username-prefixed reel", () => {
  assertEquals(isInstagramUrl("https://instagram.com/username/reel/ABC123/"), true);
});

Deno.test("isInstagramUrl - share link", () => {
  assertEquals(isInstagramUrl("https://instagram.com/share/reel/ABC123/"), true);
});

Deno.test("isInstagramUrl - instagr.am short URL", () => {
  assertEquals(isInstagramUrl("https://instagr.am/p/ABC123/"), true);
});

Deno.test("isInstagramUrl - with tracking params", () => {
  assertEquals(isInstagramUrl("https://instagram.com/reel/ABC123/?igsh=xyz"), true);
});

// Facebook tests
Deno.test("isFacebookUrl - videos URL", () => {
  assertEquals(isFacebookUrl("https://www.facebook.com/user/videos/123456/"), true);
});

Deno.test("isFacebookUrl - watch URL", () => {
  assertEquals(isFacebookUrl("https://facebook.com/watch?v=123456"), true);
});

Deno.test("isFacebookUrl - reel URL", () => {
  assertEquals(isFacebookUrl("https://facebook.com/reel/123456"), true);
});

Deno.test("isFacebookUrl - fb.watch URL", () => {
  assertEquals(isFacebookUrl("https://fb.watch/abcdefg/"), true);
});

Deno.test("isFacebookUrl - fb.gg URL", () => {
  assertEquals(isFacebookUrl("https://fb.gg/v/abcdefg/"), true);
});

// X/Twitter tests
Deno.test("isXTwitterUrl - x.com status", () => {
  assertEquals(isXTwitterUrl("https://x.com/user/status/1234567890"), true);
});

Deno.test("isXTwitterUrl - twitter.com status", () => {
  assertEquals(isXTwitterUrl("https://twitter.com/user/status/1234567890"), true);
});

Deno.test("isXTwitterUrl - www.twitter.com status", () => {
  assertEquals(isXTwitterUrl("https://www.twitter.com/user/status/123"), true);
});

Deno.test("isXTwitterUrl - mobile.twitter.com status", () => {
  assertEquals(isXTwitterUrl("https://mobile.twitter.com/user/status/456"), true);
});

Deno.test("isXTwitterUrl - profile only (reject)", () => {
  assertEquals(isXTwitterUrl("https://twitter.com/username"), false);
});

// Reddit tests
Deno.test("isRedditUrl - comments URL", () => {
  assertEquals(isRedditUrl("https://reddit.com/r/videos/comments/abc123/"), true);
});

Deno.test("isRedditUrl - redd.it short URL", () => {
  assertEquals(isRedditUrl("https://redd.it/abc123"), true);
});

Deno.test("isRedditUrl - v.redd.it video URL", () => {
  assertEquals(isRedditUrl("https://v.redd.it/xyz789"), true);
});

Deno.test("isRedditUrl - share link", () => {
  assertEquals(isRedditUrl("https://reddit.com/r/subreddit/s/abc123"), true);
});

// Vimeo tests
Deno.test("isVimeoUrl - standard URL", () => {
  assertEquals(isVimeoUrl("https://vimeo.com/123456789"), true);
});

Deno.test("isVimeoUrl - player URL", () => {
  assertEquals(isVimeoUrl("https://player.vimeo.com/video/123456789"), true);
});

Deno.test("isVimeoUrl - channel URL", () => {
  assertEquals(isVimeoUrl("https://vimeo.com/channels/staffpicks/123456789"), true);
});

// Twitch tests
Deno.test("isTwitchUrl - clips URL", () => {
  assertEquals(isTwitchUrl("https://clips.twitch.tv/AwesomeClip"), true);
});

Deno.test("isTwitchUrl - clip URL", () => {
  assertEquals(isTwitchUrl("https://twitch.tv/user/clip/ClipName"), true);
});

Deno.test("isTwitchUrl - videos URL", () => {
  assertEquals(isTwitchUrl("https://twitch.tv/videos/1234567890"), true);
});

// LinkedIn tests
Deno.test("isLinkedInUrl - posts URL", () => {
  assertEquals(isLinkedInUrl("https://linkedin.com/posts/user_activity-123"), true);
});

Deno.test("isLinkedInUrl - feed update URL", () => {
  assertEquals(isLinkedInUrl("https://linkedin.com/feed/update/urn:li:activity:123"), true);
});

// Threads tests
Deno.test("isThreadsUrl - post URL", () => {
  assertEquals(isThreadsUrl("https://threads.net/@user/post/ABC123"), true);
});

// Loom tests
Deno.test("isLoomUrl - share URL", () => {
  assertEquals(isLoomUrl("https://loom.com/share/abc123"), true);
});

// Spotify tests
Deno.test("isSpotifyUrl - episode URL", () => {
  assertEquals(isSpotifyUrl("https://open.spotify.com/episode/abc123"), true);
});

// detectPlatform tests
Deno.test("detectPlatform - TikTok", () => {
  assertEquals(detectPlatform("https://tiktok.com/@user/video/123"), "tiktok");
});

Deno.test("detectPlatform - YouTube", () => {
  assertEquals(detectPlatform("https://youtu.be/abc123"), "youtube");
});

Deno.test("detectPlatform - Instagram", () => {
  assertEquals(detectPlatform("https://instagram.com/reel/ABC123/"), "instagram");
});

Deno.test("detectPlatform - X/Twitter returns 'twitter'", () => {
  assertEquals(detectPlatform("https://x.com/user/status/123"), "twitter");
});

Deno.test("detectPlatform - unsupported URL returns null", () => {
  assertEquals(detectPlatform("https://example.com/video"), null);
});

Deno.test("detectPlatform - cleans trailing punctuation", () => {
  assertEquals(detectPlatform("https://youtu.be/abc12345678."), "youtube");
});

// isSupportedUrl tests
Deno.test("isSupportedUrl - supported platform", () => {
  assertEquals(isSupportedUrl("https://tiktok.com/@user/video/123"), true);
});

Deno.test("isSupportedUrl - unsupported URL", () => {
  assertEquals(isSupportedUrl("https://example.com"), false);
});
