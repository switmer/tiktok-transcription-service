from tiktok_scraper import get_comments

# The video URL you want to scrape
video_url = "https://www.tiktok.com/@dougweaverart/video/7415285469769895210"  # Replace with your video URL

print(f"Starting to scrape comments from: {video_url}")
comments = get_comments(video_url)

# The comments will be automatically saved to tiktok_comments.json
print("Done! Check tiktok_comments.json for the results") 