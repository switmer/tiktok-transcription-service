from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import time
import re

def setup_driver():
    """Set up Chrome driver with proper options"""
    chrome_options = Options()
    # chrome_options.add_argument('--headless=new')  # Commented out for debugging
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    
    # Additional options to avoid detection
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # More realistic user agent
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Execute CDP commands to prevent detection
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    })
    
    # Remove webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def extract_username_and_video_id(url):
    """Extract both username and video ID from a TikTok URL"""
    pattern = r'@([^/]+)/video/(\d+)'
    match = re.search(pattern, url)
    if match:
        return match.group(1), match.group(2)
    return None, None

def scroll_to_load_comments(driver, num_scrolls=3):
    """Scroll the comments section to load more comments"""
    try:
        comments_section = driver.find_element(By.CSS_SELECTOR, '[data-e2e="comment-list"]')
        for _ in range(num_scrolls):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", comments_section)
            time.sleep(1)
    except Exception as e:
        print(f"Warning: Could not scroll comments: {e}")

def get_tiktok_comments(url_or_id):
    """Fetch comments for a TikTok video by scraping the webpage"""
    print("Setting up browser...")
    driver = setup_driver()
    
    try:
        # Determine if input is URL or video ID
        if '/' in url_or_id:
            username, video_id = extract_username_and_video_id(url_or_id)
            if not username or not video_id:
                print("Could not extract username and video ID from URL")
                return None
            video_url = f'https://www.tiktok.com/@{username}/video/{video_id}'
        else:
            video_id = url_or_id
            video_url = f'https://www.tiktok.com/@user/video/{video_id}'
        
        print(f"Visiting video page: {video_url}")
        driver.get(video_url)
        
        # Add initial delay to let the page load properly
        time.sleep(5)
        
        # Wait for comments to load
        print("Waiting for comments to load...")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.css-1i7ohvi-DivCommentItemContainer'))
            )
        except Exception as e:
            print("Trying alternative comment selector...")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-e2e="comment-level-1"]'))
            )
        
        # Scroll to load more comments
        scroll_to_load_comments(driver)
        
        # Extract comments
        print("Extracting comments...")
        comments = []
        
        # Try both old and new selectors
        comment_elements = driver.find_elements(By.CSS_SELECTOR, '.css-1i7ohvi-DivCommentItemContainer')
        if not comment_elements:
            comment_elements = driver.find_elements(By.CSS_SELECTOR, '[data-e2e="comment-level-1"]')
        
        for comment in comment_elements:
            try:
                # Try both new and old selectors for each field
                try:
                    username = comment.find_element(By.CSS_SELECTOR, '.css-1665s4c-SpanUserNameText').text
                except:
                    username = comment.find_element(By.CSS_SELECTOR, '[data-e2e="comment-username-1"]').text
                
                try:
                    text = comment.find_element(By.CSS_SELECTOR, '.css-xm2h10-PCommentText').text
                except:
                    text = comment.find_element(By.CSS_SELECTOR, '[data-e2e="comment-text"]').text
                
                try:
                    likes = comment.find_element(By.CSS_SELECTOR, '.css-gb2mrc-SpanCount').text
                except:
                    likes = comment.find_element(By.CSS_SELECTOR, '[data-e2e="comment-like-count"]').text
                
                try:
                    timestamp = comment.find_element(By.CSS_SELECTOR, '.css-4tru0g-SpanCreatedTime').text
                    date_obj = datetime.strptime(timestamp, '%Y-%m-%d')
                    unix_timestamp = int(date_obj.timestamp())
                except:
                    unix_timestamp = int(time.time())
                
                comments.append({
                    'user': {'nickname': username},
                    'text': text,
                    'digg_count': likes,
                    'create_time': unix_timestamp
                })
            except Exception as e:
                print(f"Warning: Could not extract comment: {e}")
                continue
        
        return {'comments': comments, 'total': len(comments)}
        
    except Exception as e:
        print(f"Error: {e}")
        return None
        
    finally:
        driver.quit()

def print_comments(comments_data):
    """Print formatted comments"""
    if not comments_data or 'comments' not in comments_data:
        print("No comments found or invalid response")
        return
        
    print("\nComments:")
    print("-" * 50)
    
    for comment in comments_data['comments']:
        username = comment.get('user', {}).get('nickname', 'Unknown User')
        text = comment.get('text', '')
        likes = comment.get('digg_count', 0)
        timestamp = comment.get('create_time', 0)
        date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        print(f"User: {username}")
        print(f"Comment: {text}")
        print(f"Likes: {likes}")
        print(f"Date: {date}")
        print("-" * 50)

if __name__ == "__main__":
    # Example usage
    user_input = input("Enter TikTok video URL: ")
    print(f"Fetching comments...")
    comments = get_tiktok_comments(user_input)
    
    if comments:
        print_comments(comments)
        total = comments.get('total', 0)
        print(f"\nTotal comments: {total}") 