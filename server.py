import os
import json
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)

# Configuration
STORIES_FOLDER = "stories"  # Changed from "stories" to "json" as per your description
IMAGES_FOLDER = "images"
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Ensure folders exist
os.makedirs(STORIES_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_story_thumbnail(story_name, story_data):
    """Get the first image from the story as thumbnail"""
    if not story_data.get('pages'):
        return None
    
    for page in story_data['pages']:
        if page.get('images') and len(page['images']) > 0:
            first_image = page['images'][0]
            thumbnail_path = f"/images/{story_name}/{first_image}"
            return thumbnail_path
    return None

def save_story_data(story_name, data):
    """Save story data to JSON file"""
    story_file = os.path.join(STORIES_FOLDER, f"{story_name}.json")
    with open(story_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_story_data(story_name):
    """Load story data from JSON file"""
    story_file = os.path.join(STORIES_FOLDER, f"{story_name}.json")
    if os.path.exists(story_file):
        with open(story_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def parse_text_content(text_content):
    """Parse text content into paragraphs, handling newlines and unicode characters"""
    if isinstance(text_content, list):
        return text_content
    elif isinstance(text_content, str):
        # Split by newlines and filter out empty strings
        paragraphs = [p.strip() for p in text_content.split('\n') if p.strip()]
        return paragraphs
    return []

@app.route('/')
def index():
    """Serve the main HTML page"""
    # Look for the HTML file in the current directory
    html_files = ['story_viewer.html', 'index.html', 'paste.txt']
    for filename in html_files:
        if os.path.exists(filename):
            return send_file(filename)
    
    # If no HTML file found, return a simple message
    return "<h1>Story Viewer</h1><p>Please ensure story_viewer.html is in the same directory as this server.</p>"

@app.route('/api/stories')
def get_stories():
    """Get list of all stories with metadata"""
    stories = []
    
    if not os.path.exists(STORIES_FOLDER):
        return jsonify(stories)
    
    for filename in os.listdir(STORIES_FOLDER):
        if filename.endswith('.json'):
            story_name = filename[:-5]  # Remove .json extension
            story_data = load_story_data(story_name)
            
            if story_data:
                thumbnail = get_story_thumbnail(story_name, story_data)
                stories.append({
                    'name': story_name,
                    'pageCount': len(story_data.get('pages', [])),
                    'thumbnail': thumbnail
                })
    
    return jsonify(stories)

@app.route('/api/story/<story_name>')
def get_story(story_name):
    """Get specific story data"""
    story_data = load_story_data(story_name)
    if story_data:
        # Process the story data to ensure text is properly formatted
        if 'pages' in story_data:
            for page in story_data['pages']:
                if 'text' in page:
                    page['text'] = parse_text_content(page['text'])
                else:
                    page['text'] = []
                
                # Ensure images array exists
                if 'images' not in page:
                    page['images'] = []
        
        return jsonify(story_data)
    else:
        return jsonify({'error': 'Story not found'}), 404

@app.route('/api/update-paragraph', methods=['POST'])
def update_paragraph():
    """Update a specific paragraph in a story"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    paragraph_index = data.get('paragraphIndex')
    new_text = data.get('newText', '')
    
    if not all([story_name, page_number is not None, paragraph_index is not None]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    # Ensure text array exists and is properly formatted
    if 'text' not in page:
        page['text'] = []
    
    # Make sure text is a list
    page['text'] = parse_text_content(page['text'])
    
    # Extend array if necessary
    while len(page['text']) <= paragraph_index:
        page['text'].append('')
    
    # Update the paragraph
    page['text'][paragraph_index] = new_text
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True})

@app.route('/api/delete-image', methods=['POST'])
def delete_image():
    """Delete an image from a story page"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    image_index = data.get('imageIndex')
    
    if not all([story_name, page_number is not None, image_index is not None]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    if 'images' not in page or image_index >= len(page['images']):
        return jsonify({'error': 'Image not found'}), 404
    
    # Get the image filename
    image_filename = page['images'][image_index]
    
    # Delete the physical file
    image_path = os.path.join(IMAGES_FOLDER, story_name, image_filename)
    if os.path.exists(image_path):
        try:
            os.remove(image_path)
        except Exception as e:
            print(f"Error deleting image file: {e}")
    
    # Remove from story data
    page['images'].pop(image_index)
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True})

@app.route('/api/add-image', methods=['POST'])
def add_image():
    """Add a new image to a story page"""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    story_name = request.form.get('storyName')
    page_number = request.form.get('pageNumber')
    
    if not all([story_name, page_number]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        page_number = int(page_number)
    except ValueError:
        return jsonify({'error': 'Invalid page number'}), 400
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    # Create story images folder if it doesn't exist
    story_images_folder = os.path.join(IMAGES_FOLDER, story_name)
    os.makedirs(story_images_folder, exist_ok=True)
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1].lower()
    unique_filename = f"{uuid.uuid4().hex}{file_extension}"
    
    # Save the file
    file_path = os.path.join(story_images_folder, unique_filename)
    try:
        file.save(file_path)
    except Exception as e:
        return jsonify({'error': f'Failed to save file: {str(e)}'}), 500
    
    # Add to story data
    if 'images' not in page:
        page['images'] = []
    page['images'].append(unique_filename)
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True, 'filename': unique_filename})

@app.route('/api/bulk-add-images', methods=['POST'])
def bulk_add_images():
    """Add multiple images to a story page"""
    if 'images' not in request.files:
        return jsonify({'error': 'No image files provided'}), 400
    
    files = request.files.getlist('images')
    story_name = request.form.get('storyName')
    page_number = request.form.get('pageNumber')
    
    if not all([story_name, page_number]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        page_number = int(page_number)
    except ValueError:
        return jsonify({'error': 'Invalid page number'}), 400
    
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    # Create story images folder if it doesn't exist
    story_images_folder = os.path.join(IMAGES_FOLDER, story_name)
    os.makedirs(story_images_folder, exist_ok=True)
    
    # Ensure images array exists
    if 'images' not in page:
        page['images'] = []
    
    uploaded_files = []
    failed_files = []
    
    for file in files:
        if file.filename == '':
            continue
            
        if not allowed_file(file.filename):
            failed_files.append(f"{file.filename} (invalid file type)")
            continue
        
        # Generate unique filename
        file_extension = os.path.splitext(file.filename)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        
        # Save the file
        file_path = os.path.join(story_images_folder, unique_filename)
        try:
            file.save(file_path)
            page['images'].append(unique_filename)
            uploaded_files.append(unique_filename)
        except Exception as e:
            failed_files.append(f"{file.filename} (save error: {str(e)})")
    
    # Save the updated story
    if uploaded_files:
        save_story_data(story_name, story_data)
    
    return jsonify({
        'success': True,
        'uploaded_count': len(uploaded_files),
        'failed_count': len(failed_files),
        'uploaded_files': uploaded_files,
        'failed_files': failed_files
    })

@app.route('/api/reorder-image', methods=['POST'])
def reorder_image():
    """Move an image up or down in the order"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    image_index = data.get('imageIndex')
    direction = data.get('direction')  # 'up' or 'down'
    
    if not all([story_name, page_number is not None, image_index is not None, direction]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if direction not in ['up', 'down']:
        return jsonify({'error': 'Invalid direction. Must be "up" or "down"'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    if 'images' not in page or image_index >= len(page['images']):
        return jsonify({'error': 'Image not found'}), 404
    
    images = page['images']
    
    # Calculate new index
    if direction == 'up':
        new_index = image_index - 1
    else:  # direction == 'down'
        new_index = image_index + 1
    
    # Check bounds
    if new_index < 0 or new_index >= len(images):
        return jsonify({'error': 'Cannot move image in that direction'}), 400
    
    # Swap images
    images[image_index], images[new_index] = images[new_index], images[image_index]
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True, 'new_index': new_index})

@app.route('/images/<story_name>/<filename>')
def serve_image(story_name, filename):
    """Serve story images"""
    story_images_folder = os.path.join(IMAGES_FOLDER, story_name)
    file_path = os.path.join(story_images_folder, filename)
    
    if os.path.exists(file_path):
        return send_from_directory(story_images_folder, filename)
    else:
        return jsonify({'error': 'Image not found'}), 404

@app.route('/api/add-paragraph', methods=['POST'])
def add_paragraph():
    """Add a new paragraph to a story page"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    paragraph_text = data.get('paragraphText', '')
    
    if not all([story_name, page_number is not None]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    # Find the page
    page = None
    for p in story_data['pages']:
        if p.get('page_number') == page_number:
            page = p
            break
    
    if not page:
        return jsonify({'error': 'Page not found'}), 404
    
    # Ensure text array exists and is properly formatted
    if 'text' not in page:
        page['text'] = []
    
    page['text'] = parse_text_content(page['text'])
    
    # Add the new paragraph
    page['text'].append(paragraph_text)
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True, 'paragraphIndex': len(page['text']) - 1})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("Starting Story Viewer & Editor Server...")
    print("Make sure your story JSON files are in the 'json' folder")
    print("Make sure your images are in the 'images/StoryName/' folders")
    print("Server will be available at http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)