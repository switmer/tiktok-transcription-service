from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import undetected_chromedriver as uc
import time
import json
import argparse
import sys
import os
from urllib.parse import urlparse, parse_qs

def wait_and_find_element(driver, by, value, timeout=10):
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )
        return element
    except TimeoutException:
        print(f"Timeout waiting for element: {value}")
        return None

def scroll_to_load_comments(driver, comments_xpath, max_scrolls=200):
    """Scroll within the comments section to load more comments."""
    print(f"\nAttempting to load more comments (max {max_scrolls} scrolls)")
    last_comment_count = 0
    no_change_count = 0
    scroll_attempt = 0
    
    while scroll_attempt < max_scrolls:
        try:
            # Get a fresh reference to the comments section
            comments_section = wait_and_find_element(driver, By.XPATH, comments_xpath)
            
            # Get current number of comments
            comment_elements = comments_section.find_elements(By.XPATH, './/div[contains(@class, "DivCommentItemWrapper")]')
            current_comments = len(comment_elements)
            
            print(f"Current number of comments loaded: {current_comments}")
            
            if current_comments > last_comment_count:
                print(f"Found {current_comments - last_comment_count} new comments")
                last_comment_count = current_comments
                no_change_count = 0  # Reset counter when we find new comments
            else:
                no_change_count += 1
                print(f"No new comments loaded ({no_change_count}/10)")
                if no_change_count >= 10:  # More attempts before giving up
                    # Try one last aggressive scroll
                    for _ in range(3):
                        driver.execute_script("""
                            arguments[0].scrollTo({
                                top: arguments[0].scrollHeight + 1000,
                                behavior: 'auto'
                            });
                        """, comments_section)
                        time.sleep(2)
                    
                    # Check if we got any new comments after aggressive scroll
                    comment_elements = comments_section.find_elements(By.XPATH, './/div[contains(@class, "DivCommentItemWrapper")]')
                    if len(comment_elements) == current_comments:
                        print("No new comments found after multiple attempts")
                        break
                    else:
                        no_change_count = 0  # Reset if we found new comments
                        continue
            
            # Scroll in smaller increments
            scroll_height = driver.execute_script("return arguments[0].scrollHeight", comments_section)
            visible_height = driver.execute_script("return arguments[0].clientHeight", comments_section)
            current_scroll = driver.execute_script("return arguments[0].scrollTop", comments_section)
            
            # Calculate next scroll position (about 80% of visible height)
            scroll_step = int(visible_height * 0.8)
            new_scroll = min(current_scroll + scroll_step, scroll_height)
            
            # Perform the scroll
            driver.execute_script(f"""
                arguments[0].scrollTo({{
                    top: {new_scroll},
                    behavior: 'smooth'
                }});
            """, comments_section)
            
            # Add longer wait time for content to load
            time.sleep(3)
            
            # Add random pauses to mimic human behavior
            if scroll_attempt % 5 == 0:
                time.sleep(2)
            
            scroll_attempt += 1
            
        except Exception as e:
            print(f"Error while scrolling: {str(e)}")
            time.sleep(2)
            scroll_attempt += 1
            
    print(f"\nFinished loading comments. Total loaded: {last_comment_count}")

def setup_driver():
    """Initialize and return an undetected Chrome driver."""
    try:
        driver = uc.Chrome()
        return driver
    except Exception as e:
        print(f"Error setting up Chrome driver: {str(e)}")
        raise

def wait_for_comments_to_load(driver, comments_xpath):
    """Wait for comments to load by checking if skeleton placeholders are gone."""
    print("Waiting for comments to load...")
    max_attempts = 20  # Increased from 15
    attempt = 0
    
    while attempt < max_attempts:
        try:
            # Get a fresh reference to the comments section
            comments_section = wait_and_find_element(driver, By.XPATH, comments_xpath)
            
            # Check for both skeleton elements and loading indicators
            skeleton_elements = comments_section.find_elements(By.CLASS_NAME, "TUXSkeletonRectangle")
            loading_elements = comments_section.find_elements(By.XPATH, ".//*[contains(@class, 'loading') or contains(@class, 'Loading')]")
            
            if not skeleton_elements and not loading_elements:
                # Double check by waiting a bit and checking again
                time.sleep(2)
                skeleton_elements = comments_section.find_elements(By.CLASS_NAME, "TUXSkeletonRectangle")
                loading_elements = comments_section.find_elements(By.XPATH, ".//*[contains(@class, 'loading') or contains(@class, 'Loading')]")
                
                if not skeleton_elements and not loading_elements:
                    print("Comments loaded successfully!")
                    return True
            
            print(f"Comments still loading (attempt {attempt + 1}/{max_attempts})...")
            time.sleep(3)  # Increased wait time
            attempt += 1
            
        except Exception as e:
            print(f"Error while waiting for comments: {str(e)}")
            time.sleep(2)
            attempt += 1
    
    print("Warning: Comments might not have loaded completely")
    return False

def expand_replies(driver, comment_element):
    """Expand all replies for a comment."""
    try:
        # Look for "View more replies" button within this comment's container
        view_more_buttons = comment_element.find_elements(By.XPATH, './/div[contains(@class, "DivViewRepliesContainer")]//span[contains(text(), "View")]')
        
        if view_more_buttons:
            print(f"Found {len(view_more_buttons)} 'View more replies' buttons")
            for button in view_more_buttons:
                try:
                    # Scroll the button into view
                    driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", button)
                    time.sleep(1)
                    
                    # Click using JavaScript
                    driver.execute_script("arguments[0].click();", button)
                    print("Clicked 'View more replies' button")
                    time.sleep(2)  # Wait for replies to load
                except Exception as e:
                    print(f"Error clicking reply button: {str(e)}")
            return True
    except Exception as e:
        print(f"Error expanding replies: {str(e)}")
    return False

def extract_comment_data(driver, comment_element, is_reply=False):
    try:
        # Extract username
        username_element = comment_element.find_element(By.XPATH, './/div[contains(@class, "DivUsernameContentWrapper")]//p[contains(@class, "TUXText")]')
        username = username_element.text if username_element else "Unknown User"
        
        # Extract comment text
        comment_text_element = comment_element.find_element(By.XPATH, f'.//span[@data-e2e="comment-level-{2 if is_reply else 1}"]//p')
        comment_text = comment_text_element.text if comment_text_element else ""
        
        # Extract timestamp
        timestamp_element = comment_element.find_element(By.XPATH, './/span[contains(@style, "color: var(--ui-text-3)")][1]')
        timestamp = timestamp_element.text if timestamp_element else ""
        
        # Extract likes
        likes_element = comment_element.find_element(By.XPATH, './/div[contains(@class, "DivLikeContainer")]//span[contains(@style, "color: var(--ui-text-3)")]')
        likes = likes_element.text if likes_element else "0"
        
        # Get replies if this is a parent comment
        replies = []
        if not is_reply:
            try:
                # First expand replies if there's a "View more" button
                expand_replies(driver, comment_element)
                
                # Look for reply container
                reply_container = comment_element.find_element(By.XPATH, './/div[contains(@class, "DivReplyContainer")]')
                if reply_container:
                    reply_elements = reply_container.find_elements(By.XPATH, './/div[contains(@class, "DivCommentItemWrapper")]')
                    print(f"Found {len(reply_elements)} replies")
                    
                    for reply_element in reply_elements:
                        reply_data = extract_comment_data(driver, reply_element, is_reply=True)
                        if reply_data:
                            replies.append(reply_data)
            except Exception as e:
                print(f"No replies found or error getting replies: {str(e)}")
        
        comment_data = {
            'username': username,
            'text': comment_text,
            'timestamp': timestamp,
            'likes': likes
        }
        
        if replies:
            comment_data['replies'] = replies
            
        return comment_data
        
    except Exception as e:
        print(f"Error extracting {'reply' if is_reply else 'comment'} data: {str(e)}")
        return None

def get_comments(url):
    print(f"Starting to scrape comments from: {url}")
    driver = setup_driver()
    comments = []
    
    try:
        print(f"Loading URL: {url}")
        driver.get(url)
        print("Waiting for page to load...")
        time.sleep(5)
        
        # Wait for comments section
        comments_xpath = "/html/body/div[1]/div[2]/div[2]/div/div[2]/div[1]/div[2]/div[2]"
        comments_section = wait_and_find_element(driver, By.XPATH, comments_xpath)
        print("Found comments section!")
        
        if not wait_for_comments_to_load(driver, comments_xpath):
            print("Warning: Proceeding with partially loaded comments")
        
        # Scroll to load more comments
        scroll_to_load_comments(driver, comments_xpath)
        
        # Get a fresh reference to the comments section
        comments_section = wait_and_find_element(driver, By.XPATH, comments_xpath)
        
        # Find all top-level comment elements (excluding replies)
        comment_elements = comments_section.find_elements(By.XPATH, './/div[contains(@class, "DivCommentObjectWrapper")]')
        print(f"\nFound {len(comment_elements)} potential comment elements")
        
        # Process each comment
        for i, comment_element in enumerate(comment_elements, 1):
            try:
                print(f"\nProcessing comment {i}:")
                comment_data = extract_comment_data(driver, comment_element)
                if comment_data:
                    comments.append(comment_data)
                    
                # Add a small delay between processing comments
                if i % 5 == 0:
                    time.sleep(1)
                    
            except Exception as e:
                print(f"Error processing comment {i}: {str(e)}")
                continue
        
        print(f"\nTotal comments extracted: {len(comments)}")
        
        # Save comments to file
        output_file = 'tiktok_comments.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(comments, f, ensure_ascii=False, indent=2)
        print(f"Comments saved to {output_file}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        driver.quit()
    
    return comments

def extract_video_urls(driver, playlist_url):
    """Extract all video URLs from a TikTok playlist."""
    print(f"Loading playlist: {playlist_url}")
    driver.get(playlist_url)
    time.sleep(5)  # Wait for initial load
    
    video_urls = []
    last_count = 0
    no_change_count = 0
    
    while True:
        try:
            # Find all video elements using the correct class names
            video_elements = driver.find_elements(By.CSS_SELECTOR, "div.css-u5r0zg-DivVideoItemContainer")
            current_count = len(video_elements)
            
            print(f"Found {current_count} videos")
            
            if current_count > last_count:
                # Extract URLs from current set of videos
                for element in video_elements[last_count:]:
                    try:
                        # Get video description which contains the URL
                        desc_element = element.find_element(By.CSS_SELECTOR, "div.css-jl6hx0-DivVideoDescContainer h1")
                        desc_text = desc_element.text if desc_element else ""
                        
                        # Get video views for logging
                        views_element = element.find_element(By.CSS_SELECTOR, "span.css-199z3hk-SpanVideoViews")
                        views_text = views_element.text if views_element else "Unknown views"
                        
                        # Get video index
                        index_element = element.find_element(By.CSS_SELECTOR, "div.css-154zf1e-DivIndex")
                        index_text = index_element.text if index_element else "??"
                        
                        print(f"Processing video #{index_text} ({views_text})")
                        print(f"Description: {desc_text[:100]}...")  # Print first 100 chars of description
                        
                        # Click the video container to navigate to the video
                        element.click()
                        time.sleep(3)  # Wait for navigation
                        
                        # Get the current URL after navigation
                        video_url = driver.current_url
                        if video_url and '/video/' in video_url and video_url not in video_urls:
                            video_urls.append(video_url)
                            print(f"Added video URL: {video_url}")
                        
                        # Navigate back to the playlist
                        driver.back()
                        time.sleep(2)  # Wait for playlist page to reload
                    
                    except Exception as e:
                        print(f"Error processing video element: {str(e)}")
                        # Try to ensure we're back on the playlist page
                        if '/playlist/' not in driver.current_url:
                            driver.get(playlist_url)
                            time.sleep(3)
                        continue
                
                last_count = current_count
                no_change_count = 0
            else:
                no_change_count += 1
                print(f"No new videos found (attempt {no_change_count}/5)")
                if no_change_count >= 5:
                    # Try one last aggressive scroll
                    driver.execute_script("""
                        window.scrollTo({
                            top: document.body.scrollHeight + 1000,
                            behavior: 'smooth'
                        });
                    """)
                    time.sleep(3)
                    
                    # Check one last time
                    video_elements = driver.find_elements(By.CSS_SELECTOR, "div.css-u5r0zg-DivVideoItemContainer")
                    if len(video_elements) == current_count:
                        print("No more videos found after final scroll")
                        break
                    else:
                        no_change_count = 0  # Reset if we found new videos
            
            # Scroll smoothly
            driver.execute_script("""
                window.scrollTo({
                    top: document.body.scrollHeight,
                    behavior: 'smooth'
                });
            """)
            time.sleep(2)
            
        except Exception as e:
            print(f"Error while extracting video URLs: {str(e)}")
            break
    
    print(f"\nTotal videos found in playlist: {len(video_urls)}")
    return video_urls

def process_playlist(playlist_url):
    """Process all videos in a TikTok playlist."""
    driver = setup_driver()
    all_comments = {}
    
    try:
        # Create output directory for playlist
        playlist_name = "tiktok_playlist_comments"
        os.makedirs(playlist_name, exist_ok=True)
        
        # Extract all video URLs from playlist
        video_urls = extract_video_urls(driver, playlist_url)
        
        # Process each video
        for i, video_url in enumerate(video_urls, 1):
            print(f"\nProcessing video {i}/{len(video_urls)}")
            print(f"URL: {video_url}")
            
            try:
                # Extract video ID from URL
                parsed_url = urlparse(video_url)
                video_id = parsed_url.path.split('/')[-1]
                
                # Get comments for this video
                comments = get_comments(video_url)
                
                # Save comments for this video
                output_file = os.path.join(playlist_name, f"video_{video_id}_comments.json")
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(comments, f, ensure_ascii=False, indent=2)
                
                print(f"Saved comments to {output_file}")
                
                # Store in all_comments dictionary
                all_comments[video_id] = comments
                
                # Add a delay between videos
                time.sleep(5)
                
            except Exception as e:
                print(f"Error processing video {video_url}: {str(e)}")
                continue
        
        # Save summary of all comments
        summary_file = os.path.join(playlist_name, "playlist_summary.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                'playlist_url': playlist_url,
                'total_videos': len(video_urls),
                'processed_videos': len(all_comments),
                'comments_by_video': all_comments
            }, f, ensure_ascii=False, indent=2)
        
        print(f"\nPlaylist processing complete. Summary saved to {summary_file}")
        
    except Exception as e:
        print(f"Error processing playlist: {str(e)}")
    finally:
        driver.quit()
    
    return all_comments

def main():
    parser = argparse.ArgumentParser(description='Scrape comments from TikTok videos')
    parser.add_argument('input', help='The TikTok video URL, playlist URL, or path to a text file containing URLs')
    parser.add_argument('-o', '--output', help='Output directory name (default: tiktok_comments)', 
                       default='tiktok_comments')
    parser.add_argument('--batch', action='store_true', help='Process input as a text file containing URLs')
    
    args = parser.parse_args()
    
    if not args.input:
        print("Error: Please provide a TikTok URL or file path")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output, exist_ok=True)
    
    if args.batch:
        # Process URLs from text file
        try:
            with open(args.input, 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
            
            print(f"Found {len(urls)} URLs in {args.input}")
            for i, url in enumerate(urls, 1):
                print(f"\nProcessing URL {i}/{len(urls)}")
                print(f"URL: {url}")
                
                try:
                    # Extract video ID for filename
                    video_id = url.split('/')[-1].strip()
                    output_file = os.path.join(args.output, f"comments_{video_id}.json")
                    
                    # Get comments
                    comments = get_comments(url)
                    
                    # Save to file
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(comments, f, ensure_ascii=False, indent=2)
                    
                    print(f"Saved comments to {output_file}")
                    
                    # Add delay between videos
                    if i < len(urls):
                        print("Waiting before next video...")
                        time.sleep(3)
                        
                except Exception as e:
                    print(f"Error processing {url}: {str(e)}")
                    continue
                    
        except Exception as e:
            print(f"Error reading file {args.input}: {str(e)}")
            sys.exit(1)
            
    elif '/playlist/' in args.input:
        print("Processing playlist...")
        process_playlist(args.input)
    else:
        print("Processing single video...")
        get_comments(args.input)

if __name__ == "__main__":
    main() 