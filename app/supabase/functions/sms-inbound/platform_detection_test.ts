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
  isInstagramStoriesUrl,
  isWebPageUrl,
  extractYouTubeVideoId,
  canonicalizeYouTubeUrl,
  youtubeIdIlikePattern,
  linksMatchForRetry,
  pickRetryTask,
  classifyExistingTask,
  isSupportedUrl,
  isKnownPlatformUrl,
  getInstagramStoriesMessage,
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

Deno.test("detectPlatform - generic http URL returns 'web'", () => {
  assertEquals(detectPlatform("https://example.com/video"), "web");
});

Deno.test("detectPlatform - Instagram reel shortcode", () => {
  assertEquals(detectPlatform("https://www.instagram.com/reel/DfVWPIwFJz_/"), "instagram");
});

Deno.test("detectPlatform - cleans trailing punctuation", () => {
  assertEquals(detectPlatform("https://youtu.be/abc12345678."), "youtube");
});

// isSupportedUrl tests
Deno.test("isSupportedUrl - supported platform", () => {
  assertEquals(isSupportedUrl("https://tiktok.com/@user/video/123"), true);
});

Deno.test("isSupportedUrl - generic web page is now supported", () => {
  assertEquals(isSupportedUrl("https://example.com"), true);
});

Deno.test("isSupportedUrl - non-URL returns false", () => {
  assertEquals(isSupportedUrl("not a url"), false);
});

// Instagram Stories tests (not supported)
Deno.test("isInstagramStoriesUrl - detects stories URL", () => {
  assertEquals(isInstagramStoriesUrl("https://www.instagram.com/stories/username/"), true);
});

Deno.test("isInstagramStoriesUrl - detects stories URL without www", () => {
  assertEquals(isInstagramStoriesUrl("https://instagram.com/stories/username/"), true);
});

Deno.test("isInstagramStoriesUrl - rejects reel URL", () => {
  assertEquals(isInstagramStoriesUrl("https://instagram.com/reel/ABC123/"), false);
});

Deno.test("isInstagramStoriesUrl - rejects post URL", () => {
  assertEquals(isInstagramStoriesUrl("https://instagram.com/p/ABC123/"), false);
});

// Web page URL tests
Deno.test("isWebPageUrl - accepts https URL", () => {
  assertEquals(isWebPageUrl("https://example.com/page"), true);
});

Deno.test("isWebPageUrl - accepts http URL", () => {
  assertEquals(isWebPageUrl("http://example.com/page"), true);
});

Deno.test("isWebPageUrl - rejects non-URL", () => {
  assertEquals(isWebPageUrl("not a url"), false);
});

Deno.test("isWebPageUrl - rejects empty string", () => {
  assertEquals(isWebPageUrl(""), false);
});

Deno.test("isWebPageUrl - accepts URL with query params", () => {
  assertEquals(isWebPageUrl("https://example.com/page?id=123"), true);
});

// detectPlatform - web page tests (stored as 'web' in DB)
Deno.test("detectPlatform - generic web page returns 'web'", () => {
  assertEquals(detectPlatform("https://example.com/page"), "web");
});

Deno.test("detectPlatform - Shopify product page returns 'web'", () => {
  assertEquals(detectPlatform("https://mystore.myshopify.com/products/item"), "web");
});

Deno.test("detectPlatform - blog post returns 'web'", () => {
  assertEquals(detectPlatform("https://ed.codes/blog/how-to-embed-video"), "web");
});

Deno.test("detectPlatform - w3schools returns 'web'", () => {
  assertEquals(detectPlatform("https://www.w3schools.com/html/html5_video.asp"), "web");
});

// isKnownPlatformUrl tests
Deno.test("isKnownPlatformUrl - TikTok returns true", () => {
  assertEquals(isKnownPlatformUrl("https://tiktok.com/@user/video/123"), true);
});

Deno.test("isKnownPlatformUrl - YouTube returns true", () => {
  assertEquals(isKnownPlatformUrl("https://youtu.be/abc123"), true);
});

Deno.test("isKnownPlatformUrl - generic web page returns false", () => {
  assertEquals(isKnownPlatformUrl("https://example.com/page"), false);
});

Deno.test("isKnownPlatformUrl - non-URL returns false", () => {
  assertEquals(isKnownPlatformUrl("not a url"), false);
});

// getInstagramStoriesMessage tests
Deno.test("getInstagramStoriesMessage - returns helpful message", () => {
  const message = getInstagramStoriesMessage();
  assertEquals(message.includes("Stories"), true);
  assertEquals(message.includes("Reel"), true);
});

const LIVE = "https://www.youtube.com/live/LzZ_FptHWqs?is=qIAcJzCrcYqh_KF9";
const CANONICAL = "https://www.youtube.com/watch?v=LzZ_FptHWqs";

Deno.test("canonicalizeYouTubeUrl - every share form is the same watch URL", () => {
  const forms = [
    LIVE,
    "https://www.youtube.com/watch?v=LzZ_FptHWqs",
    "https://www.youtube.com/watch?list=PLxxx&v=LzZ_FptHWqs",
    "https://youtu.be/LzZ_FptHWqs?si=abc&t=12",
    "https://www.youtube.com/shorts/LzZ_FptHWqs?pp=ygU",
    "https://www.youtube.com/embed/LzZ_FptHWqs",
    "https://m.youtube.com/watch?v=LzZ_FptHWqs&pp=1&is=other",
    "https://music.youtube.com/watch?v=LzZ_FptHWqs&si=track",
    "https://youtube.com/live/LzZ_FptHWqs/",
  ];
  for (const form of forms) {
    assertEquals(canonicalizeYouTubeUrl(form), CANONICAL);
    assertEquals(extractYouTubeVideoId(form), "LzZ_FptHWqs");
  }
});

Deno.test("extractYouTubeVideoId - does not treat the is= token as the video id", () => {
  assertEquals(extractYouTubeVideoId(LIVE), "LzZ_FptHWqs");
  assertEquals(extractYouTubeVideoId("https://www.youtube.com/watch?is=qIAcJzCrcYqh_KF9"), null);
});

Deno.test("youtubeIdIlikePattern - escapes underscore wildcards", () => {
  assertEquals(youtubeIdIlikePattern("LzZ_FptHWqs"), "%LzZ\\_FptHWqs%");
});

Deno.test("free retry matches a live share link with a different is= param", () => {
  const rows = [
    {
      task_id: "other",
      status: "failed",
      url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      video_id: "dQw4w9WgXcQ",
      title: "Different video",
    },
    {
      task_id: "failed-live",
      status: "failed",
      url: "https://www.youtube.com/live/LzZ_FptHWqs?is=oldToken",
      video_id: null,
      title: "Live",
    },
  ];
  // Newest-first list: the failed live row is the match, not the other video.
  const incoming = "https://youtu.be/LzZ_FptHWqs?is=qIAcJzCrcYqh_KF9";
  const match = pickRetryTask(incoming, rows);
  assertEquals(match?.task_id, "failed-live");
  assertEquals(classifyExistingTask(match?.status), "free_retry");
  assertEquals(linksMatchForRetry(incoming, rows[1].url, rows[1].video_id), true);
  assertEquals(linksMatchForRetry(incoming, rows[0].url, rows[0].video_id), false);
});

Deno.test("retry match treats watch, shorts, embed, m., and music. as one video", () => {
  const stored = "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=abc";
  for (const incoming of [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ?pp=1",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=zzz",
  ]) {
    assertEquals(linksMatchForRetry(incoming, stored, null), true);
  }
});

Deno.test("a different video does not qualify as a free retry", () => {
  const rows = [{
    task_id: "failed-live",
    status: "failed",
    url: LIVE,
    video_id: null,
    title: "Live",
  }];
  const match = pickRetryTask("https://www.youtube.com/watch?v=dQw4w9WgXcQ&is=something", rows);
  assertEquals(match, null);
  assertEquals(classifyExistingTask(undefined), "none");
});

Deno.test("completed and in-flight matches are not free retries", () => {
  assertEquals(classifyExistingTask("completed"), "completed");
  assertEquals(classifyExistingTask("pending"), "inflight");
  assertEquals(classifyExistingTask("processing"), "inflight");
  assertEquals(classifyExistingTask("error"), "free_retry");
});
