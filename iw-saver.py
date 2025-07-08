import os
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException
import re
from urllib.parse import urljoin, urlparse
from pathlib import Path
import hashlib

class InfiniteWorldsScraper:
    def __init__(self):
        self.driver = None
        self.config = self.load_config()
        self.stories_folder = "stories"
        self.images_folder = "images"
        self.ensure_folders_exist()
        
    def load_config(self):
        """Load configuration from config.json"""
        config_file = "config.json"
        default_config = {
            "auto_continue": False,
            "wait_time": 3,
            "max_pages": 100,
            "download_images": True,
            "max_image_swaps": 10,
            "image_swap_wait": 2,
            "email": "example@gmail.com",
            "password": "password"
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Add new config options if they don't exist
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                # Save updated config
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)
                return config
        else:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
            print(f"Created default config file: {config_file}")
            return default_config
    
    def ensure_folders_exist(self):
        """Create necessary folders if they don't exist"""
        os.makedirs(self.stories_folder, exist_ok=True)
        os.makedirs(self.images_folder, exist_ok=True)
    
    def get_existing_stories(self):
        """Get list of existing story files"""
        stories = []
        for file in os.listdir(self.stories_folder):
            if file.endswith('.json'):
                stories.append(file[:-5])  # Remove .json extension
        return stories
    
    def select_story(self):
        """Allow user to select or create a story"""
        existing_stories = self.get_existing_stories()
        
        print("\n=== Story Selection ===")
        if existing_stories:
            print("Existing stories:")
            for i, story in enumerate(existing_stories, 1):
                print(f"{i}. {story}")
            print(f"{len(existing_stories) + 1}. Create new story")
            
            while True:
                try:
                    choice = input(f"\nSelect option (1-{len(existing_stories) + 1}): ").strip()
                    choice_num = int(choice)
                    
                    if 1 <= choice_num <= len(existing_stories):
                        return existing_stories[choice_num - 1]
                    elif choice_num == len(existing_stories) + 1:
                        break
                    else:
                        print("Invalid choice. Please try again.")
                except ValueError:
                    print("Please enter a valid number.")
        
        # Create new story
        while True:
            story_name = input("Enter new story name: ").strip()
            if story_name:
                # Clean story name for filename
                story_name = re.sub(r'[<>:"/\\|?*]', '_', story_name)
                return story_name
            print("Story name cannot be empty.")
    
    def setup_driver(self):
        """Setup Brave browser with Selenium"""
        options = Options()
        # Path to Brave browser executable (adjust as needed)
        brave_path = self.find_brave_path()
        if brave_path:
            options.binary_location = brave_path
        
        # Add options for better stability
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            print("Brave browser opened successfully!")
            return True
        except Exception as e:
            print(f"Error opening Brave browser: {e}")
            print("Make sure you have ChromeDriver installed and Brave browser is available.")
            return False
    
    def find_brave_path(self):
        """Find Brave browser executable path"""
        possible_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            r"/usr/bin/brave-browser",
            r"/snap/bin/brave"
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None
    
    def load_story_data(self, story_name):
        """Load existing story data or create new structure"""
        story_file = os.path.join(self.stories_folder, f"{story_name}.json")
        
        if os.path.exists(story_file):
            with open(story_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {"story_name": story_name, "pages": []}
    
    def save_story_data(self, story_name, data):
        """Save story data to JSON file"""
        story_file = os.path.join(self.stories_folder, f"{story_name}.json")
        with open(story_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"Story data saved to {story_file}")
    
    def get_image_hash(self, img_url):
        """Get a hash of the image content for comparison"""
        try:
            response = requests.get(img_url, timeout=10)
            response.raise_for_status()
            return hashlib.md5(response.content).hexdigest()
        except Exception as e:
            print(f"Error getting image hash: {e}")
            return None
    
    def download_image(self, img_url, story_name, page_number, image_index=0):
        """Download image and save to appropriate folder"""
        if not self.config.get("download_images", True):
            return None
            
        story_images_folder = os.path.join(self.images_folder, story_name)
        os.makedirs(story_images_folder, exist_ok=True)
        
        try:
            # Get file extension from URL
            parsed_url = urlparse(img_url)
            file_extension = os.path.splitext(parsed_url.path)[1] or '.jpg'
            
            filename = f"page_{page_number}_{image_index}{file_extension}"
            filepath = os.path.join(story_images_folder, filename)
            
            response = requests.get(img_url, timeout=10)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            print(f"Downloaded image: {filename}")
            return filename
        except Exception as e:
            print(f"Error downloading image: {e}")
            return None
    
    def find_swap_image_button(self):
        """Find the 'Swap image' button"""
        try:
            # Look for elements containing "Swap image" text
            swap_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Swap image')]")
            
            for element in swap_elements:
                # Check if the element is clickable (button or has click handler)
                if element.tag_name.lower() in ['button', 'a'] or element.get_attribute('onclick'):
                    return element
                
                # Look for clickable parent elements
                parent = element.find_element(By.XPATH, "..")
                if parent.tag_name.lower() in ['button', 'a'] or parent.get_attribute('onclick'):
                    return parent
            
            return None
        except Exception as e:
            print(f"Error finding swap image button: {e}")
            return None
    
    def find_image_in_swap_div(self):
        """Find the image in the same div as the 'Swap image' button"""
        try:
            # Find the 'Swap image' text element
            swap_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Swap image')]")
            
            for swap_element in swap_elements:
                current_element = swap_element
                # Traverse up the DOM tree to find an image
                for level in range(10):  # Check up to 10 parent levels
                    try:
                        # Look for img elements in the current element
                        img_elements = current_element.find_elements(By.TAG_NAME, "img")
                        
                        for img in img_elements:
                            src = img.get_attribute("src")
                            if src and ("infinite-worlds-images" in src or "http" in src):
                                # Found a valid image
                                return img
                        
                        # Move to parent element
                        current_element = current_element.find_element(By.XPATH, "..")
                    except Exception:
                        break
            
            return None
        except Exception as e:
            print(f"Error finding image in swap div: {e}")
            return None
    
    def extract_turn_number(self):
        """Extract turn number from page"""
        try:
            # Look for text containing "turn" followed by a number
            page_text = self.driver.find_element(By.TAG_NAME, "body").text
            turn_match = re.search(r'turn\s+(\d+)', page_text, re.IGNORECASE)
            
            if turn_match:
                return int(turn_match.group(1))
            else:
                print("Could not find turn number on page")
                return None
        except Exception as e:
            print(f"Error extracting turn number: {e}")
            return None
    
    def scrape_multiple_images(self, story_name, page_number):
        """Scrape multiple images by swapping through them"""
        downloaded_images = []
        seen_image_hashes = set()
        seen_image_urls = set()
        max_swaps = self.config.get("max_image_swaps", 10)
        wait_time = self.config.get("image_swap_wait", 2)
        
        print(f"Starting image collection for page {page_number}")
        
        for swap_count in range(max_swaps + 1):  # +1 for the initial image
            try:
                # Wait for image to load
                time.sleep(wait_time)
                
                # Find the current image
                img_element = self.find_image_in_swap_div()
                
                if img_element:
                    img_url = img_element.get_attribute("src")
                    
                    if img_url and img_url not in seen_image_urls:
                        print(f"Found new image (attempt {swap_count + 1}): {img_url}")
                        
                        # Check if this is a unique image by hash
                        img_hash = self.get_image_hash(img_url)
                        
                        if img_hash and img_hash not in seen_image_hashes:
                            # Download the image
                            filename = self.download_image(img_url, story_name, page_number, len(downloaded_images))
                            
                            if filename:
                                downloaded_images.append(filename)
                                seen_image_hashes.add(img_hash)
                                seen_image_urls.add(img_url)
                                print(f"Downloaded unique image {len(downloaded_images)}: {filename}")
                            else:
                                print("Failed to download image")
                        else:
                            print("Image already seen (by hash), stopping swap cycle")
                            break
                    else:
                        if not img_url:
                            print("No image URL found (possibly blank image)")
                        else:
                            print("Image URL already seen, stopping swap cycle")
                            break
                else:
                    print("No image found on page")
                    if swap_count == 0:
                        # If we can't find any image on the first try, break
                        break
                
                # If this isn't the last iteration, try to swap to next image
                if swap_count < max_swaps:
                    swap_button = self.find_swap_image_button()
                    if swap_button:
                        print("Clicking swap image button...")
                        swap_button.click()
                        time.sleep(wait_time)  # Wait for new image to load
                    else:
                        print("No swap image button found, ending image collection")
                        break
                        
            except Exception as e:
                print(f"Error during image swap {swap_count + 1}: {e}")
                continue
        
        print(f"Collected {len(downloaded_images)} unique images for page {page_number}")
        return downloaded_images
    
    def scrape_page(self, story_name, prev_page_number):
        """Scrape current page for content"""
        try:
            # Extract turn number (page number)
            new_number = False
            while new_number == False:
                page_number = self.extract_turn_number()
                print(f"Page number: {page_number}")
                if page_number is None:
                    page_number = len(self.story_data["pages"]) + 1
                    print(f"Using sequential page number: {page_number}")
                
                if page_number == prev_page_number:
                    print(f"Page number hasn't changed, trying again in 5 seconds")
                    time.sleep(5)
                else:
                    new_number = True
            
            # Extract paragraph elements
            paragraphs = []
            try:
                # Look for paragraph elements in the content area
                p_elements = self.driver.find_elements(By.TAG_NAME, "p")
                for p in p_elements:
                    text = p.text.strip()
                    if text:
                        paragraphs.append(text)
            except Exception as e:
                print(f"Error extracting paragraphs: {e}")
            
            # Extract multiple images through swapping
            image_filenames = self.scrape_multiple_images(story_name, page_number)
            
            # Create page data
            page_data = {
                "page_number": page_number,
                "text": paragraphs,
                "images": image_filenames
            }
            
            print(f"Scraped page {page_number}: {len(paragraphs)} paragraphs, {len(image_filenames)} images")
            return page_data
            
        except Exception as e:
            print(f"Error scraping page: {e}")
            return None
    
    def find_next_button(self):
        """Find and click the 'Next turn' button"""
        try:
            # Look for "Next turn" text
            next_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Next turn')]")
            
            if next_elements:
                next_elements[0].click()
                return True
            else:
                print("Could not find 'Next turn' button")
                return False
                
        except Exception as e:
            print(f"Error finding next button: {e}")
            return False
    
    def safe_click_element(self, element):
        """Safely click an element using multiple methods"""
        try:
            # Method 1: Regular click
            element.click()
            return True
        except ElementNotInteractableException:
            try:
                # Method 2: JavaScript click
                self.driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                try:
                    # Method 3: Action chains
                    ActionChains(self.driver).move_to_element(element).click().perform()
                    return True
                except Exception:
                    return False
        except Exception:
            return False
    
    def safe_input_text(self, element, text):
        """Safely input text into an element"""
        try:
            # Method 1: Click and clear, then send keys
            element.click()
            element.clear()
            element.send_keys(text)
            return True
        except ElementNotInteractableException:
            try:
                # Method 2: Focus with JavaScript and use send_keys
                self.driver.execute_script("arguments[0].focus();", element)
                element.clear()
                element.send_keys(text)
                return True
            except Exception:
                try:
                    # Method 3: Set value with JavaScript
                    self.driver.execute_script("arguments[0].value = arguments[1];", element, text)
                    # Trigger change event
                    self.driver.execute_script("arguments[0].dispatchEvent(new Event('change'));", element)
                    return True
                except Exception:
                    return False
        except Exception:
            return False
    
    def find_input_field(self, field_type="email"):
        """Find input field by type or common attributes"""
        try:
            # Method 1: Find by type attribute
            if field_type == "email":
                selectors = [
                    "input[type='email']",
                    "input[placeholder*='email']",
                    "input[name*='email']",
                    "input[id*='email']"
                ]
            elif field_type == "password":
                selectors = [
                    "input[type='password']",
                    "input[placeholder*='password']",
                    "input[name*='password']",
                    "input[id*='password']"
                ]
            else:
                return None
            
            for selector in selectors:
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if element.is_displayed():
                        return element
                except NoSuchElementException:
                    continue
            
            return None
        except Exception as e:
            print(f"Error finding {field_type} field: {e}")
            return None
    
    def perform_login(self):
        """Perform automatic login sequence"""
        try:
            print("Attempting automatic login...")
            
            # Get credentials from config
            email = self.config.get("email", "")
            password = self.config.get("password", "")
            
            if not email or not password or email == "example@gmail.com":
                print("Please update your email and password in config.json")
                return False
            
            # Wait for page to fully load
            time.sleep(8)
            
            # Step 1: Find and click "Play now" button
            print("Looking for 'Play now' button...")
            play_now_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Play now')]")
            
            if not play_now_elements:
                print("Could not find 'Play now' button, checking if already logged in...")
                return True  # Might already be logged in
            
            # Click the "Play now" button
            play_button = self.find_clickable_parent(play_now_elements[0])
            
            print("Clicking 'Play now' button...")
            if not self.safe_click_element(play_button):
                print("Failed to click 'Play now' button")
                return False
            
            # Step 2: Wait for popup to appear
            print("Waiting for login popup...")
            time.sleep(5)
            
            # Step 3: Find and click "Yes, log me in please"
            print("Looking for 'Yes, log me in please' text...")
            login_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Yes, log me in please!')]")
            
            if not login_elements:
                print("Could not find 'Yes, log me in please' text")
                return False
            
            # Find the clickable parent (button containing the span)
            login_button = self.find_clickable_parent(login_elements[0])
            
            print("Clicking 'Yes, log me in please'...")
            if not self.safe_click_element(login_button):
                print("Failed to click 'Yes, log me in please'")
                return False
            
            # Step 4: Wait for login form to appear
            print("Waiting for login form...")
            time.sleep(5)
            
            # Step 5: Fill in email field
            print("Looking for email field...")
            email_field = self.find_input_field("email")
            
            if email_field:
                print("Filling email field...")
                if not self.safe_input_text(email_field, email):
                    print("Failed to fill email field")
                    return False
            else:
                print("Could not find email field")
                return False
            
            # Step 6: Fill in password field
            print("Looking for password field...")
            password_field = self.find_input_field("password")
            
            if password_field:
                print("Filling password field...")
                if not self.safe_input_text(password_field, password):
                    print("Failed to fill password field")
                    return False
            else:
                print("Could not find password field")
                return False
            
            # Step 7: Click "Log In" button
            print("Looking for 'Log In' button...")
            login_submit_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Log In')]")
            
            if not login_submit_elements:
                print("Could not find 'Log In' button")
                return False
            
            # Find the clickable parent
            login_submit_button = self.find_clickable_parent(login_submit_elements[0])
            
            print("Clicking 'Log In' button...")
            if not self.safe_click_element(login_submit_button):
                print("Failed to click 'Log In' button")
                return False
            
            # Step 8: Wait for login to complete
            print("Waiting for login to complete...")
            time.sleep(8)
            
            print("Login sequence completed successfully!")
            return True
            
        except Exception as e:
            print(f"Error during login: {e}")
            print("You may need to log in manually...")
            return False
    
    def run(self):
        """Main scraping loop"""
        print("=== Infinite Worlds Scraper ===")
        
        # Setup
        story_name = self.select_story()
        self.story_data = self.load_story_data(story_name)
        
        if not self.setup_driver():
            return
        
        try:
            # Navigate to the site
            self.driver.get("https://infiniteworlds.app/")
            print("Opened Infinite Worlds app")
            
            # Perform automatic login
            login_successful = self.perform_login()
            
            if login_successful:
                print("Login completed. Please navigate to your story and the starting page.")
            else:
                print("Automatic login failed. Please log in manually and navigate to your story.")
            
            # Wait for user to navigate to story
            input("\nPlease navigate to your story and the starting page in the browser, then press Enter to continue...")
            
            page_count = 0
            max_pages = self.config.get("max_pages", 100)
            
            prev_page_number = -1
                
            while page_count < max_pages:
                print(f"\n--- Scraping page {page_count + 1} ---")
                
                # Wait for page to load
                time.sleep(self.config.get("wait_time", 3))
                
                # Scrape current page
                page_data = self.scrape_page(story_name, prev_page_number)
                
                if page_data:
                    # Check if page already exists
                    existing_page = next((p for p in self.story_data["pages"] if p["page_number"] == page_data["page_number"]), None)
                    
                    prev_page_number = page_data["page_number"]
                    
                    if existing_page:
                        print(f"Page {page_data['page_number']} already exists, updating...")
                        existing_page.update(page_data)
                    else:
                        self.story_data["pages"].append(page_data)
                    
                    # Save after each page
                    self.save_story_data(story_name, self.story_data)
                
                # Try to find next button
                if not self.find_next_button():
                    print("No more pages to scrape (no 'Next turn' button found)")
                    break
                
                page_count += 1
                
                # Check if we should continue automatically
                if not self.config.get("auto_continue", False):
                    continue_choice = input("Continue to next page? (y/n/q to quit): ").strip().lower()
                    if continue_choice == 'q':
                        break
                    elif continue_choice != 'y':
                        continue
                else:
                    print("Auto-continuing to next page...")
            
            print(f"\nScraping completed! Processed {page_count} pages.")
            
        finally:
            if self.driver:
                input("Press Enter to close the browser...")
                self.driver.quit()
                
    def find_clickable_parent(self, element):
        """Find the nearest clickable parent element (button, a, or element with click handler)"""
        try:
            current = element
            max_levels = 5  # Don't go too far up the DOM tree
            
            for level in range(max_levels):
                # Check if current element is clickable
                if self.is_clickable_element(current):
                    return current
                
                # Move to parent
                try:
                    current = current.find_element(By.XPATH, "..")
                except Exception:
                    break
            
            # If no clickable parent found, return the original element
            return element
            
        except Exception as e:
            print(f"Error finding clickable parent: {e}")
            return element

    def is_clickable_element(self, element):
        """Check if an element is clickable"""
        try:
            tag_name = element.tag_name.lower()
            
            # Check if it's a naturally clickable element
            if tag_name in ['button', 'a', 'input']:
                return True
            
            # Check if it has click-related attributes
            if element.get_attribute('onclick'):
                return True
                
            # Check if it has cursor pointer style
            cursor_style = element.value_of_css_property('cursor')
            if cursor_style == 'pointer':
                return True
                
            # Check for common clickable classes
            class_name = element.get_attribute('class') or ''
            if any(keyword in class_name.lower() for keyword in ['button', 'btn', 'clickable', 'click']):
                return True
                
            return False
            
        except Exception:
            return False

if __name__ == "__main__":
    scraper = InfiniteWorldsScraper()
    scraper.run()