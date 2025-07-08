# Infinite Worlds Scraper

A Python Selenium project that scrapes stories from the Infinite Worlds app, automatically navigating through pages and saving content to JSON files with downloaded images.

## Features

- **Story Management**: Select existing stories or create new ones
- **Automatic Navigation**: Clicks "Next turn" buttons to navigate through story pages
- **Content Extraction**: Grabs paragraph text and images from each page
- **JSON Storage**: Saves story data in organized JSON format with page numbers
- **Image Download**: Downloads and organizes images in separate folders
- **Configurable**: Control auto-continuation, wait times, and more

## Setup

### Prerequisites

1. **Python 3.7+** installed
2. **Brave Browser** installed
3. **ChromeDriver** installed and in your PATH
   - Download from: https://chromedriver.chromium.org/
   - Make sure the version matches your Chrome/Brave version

### Installation

1. Clone or download the project files
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

Edit `config.json` to customize behavior:

```json
{
  "auto_continue": false,     // Auto-click "Next turn" or wait for user input
  "wait_time": 3,            // Seconds to wait between page loads
  "max_pages": 100,          // Maximum pages to scrape per session
  "download_images": true    // Whether to download images
}
```

## Usage

1. Run the scraper:
   ```bash
   python scraper.py
   ```

2. **Story Selection**: Choose an existing story or create a new one

3. **Browser Navigation**: 
   - Brave browser will open to https://infiniteworlds.app/
   - Navigate to your desired story and starting page
   - Press Enter in the console to start scraping

4. **Automatic Scraping**: The script will:
   - Extract the turn number from the page
   - Grab all paragraph text
   - Download the story image
   - Click "Next turn" and repeat
   - Save progress after each page

## File Structure

```
project/
├── scraper.py          # Main scraping script
├── config.json         # Configuration settings
├── requirements.txt    # Python dependencies
├── stories/           # JSON files for each story
│   ├── story1.json
│   └── story2.json
└── images/            # Downloaded images organized by story
    ├── story1/
    │   ├── page_1.jpg
    │   └── page_2.jpg
    └── story2/
        └── page_1.jpg
```

## JSON Format

Each story JSON file contains:

```json
{
  "story_name": "My Story",
  "pages": [
    {
      "page_number": 245,
      "text": [
        "Paragraph 1 content...",
        "Paragraph 2 content..."
      ],
      "images": ["page_245.jpg"]
    }
  ]
}
```

## Troubleshooting

### Common Issues

1. **Browser not opening**: Make sure ChromeDriver is installed and Brave browser path is correct
2. **Elements not found**: The website structure may have changed - update the selectors in the code
3. **Images not downloading**: Check your internet connection and image URLs

### Browser Path Issues

If Brave isn't found automatically, you can manually set the path in the `find_brave_path()` method or add your custom path to the `possible_paths` list.

## Notes

- The script is designed to be interrupted and resumed - it saves progress after each page
- Existing pages with the same page number will be updated rather than duplicated
- The script respects the website by adding delays between requests
- Images are downloaded with descriptive filenames based on page numbers

## Safety Features

- Maximum page limit to prevent infinite loops
- Error handling for network issues and missing elements
- Progress saving to prevent data loss
- User confirmation options for manual control
# InfiniteWorlds-Scraper
