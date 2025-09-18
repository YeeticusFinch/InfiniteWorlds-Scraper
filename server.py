import os
import json
import shutil
import base64
import wave
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from werkzeug.utils import secure_filename
import uuid
import threading
import time
from TTS.utils.manage import ModelManager
import subprocess
import traceback
import subprocess

# TTS imports
try:
    from TTS.api import TTS
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("Warning: Coqui TTS not installed. TTS functionality will be disabled.")

app = Flask(__name__)

# Configuration
STORIES_FOLDER = "stories"  # Changed from "stories" to "json" as per your description
IMAGES_FOLDER = "images"
AUDIO_FOLDER = "audio"
UPLOAD_FOLDER = "uploads"
TTS_MODELS_FOLDER = "tts_models"  # Folder containing TTS voice models
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_AUDIO_EXTENSIONS = {'wav', 'mp3', 'ogg', 'webm'}

# Ensure folders exist
os.makedirs(STORIES_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TTS_MODELS_FOLDER, exist_ok=True)

# Path where Coqui stores models (usually ~/.local/share/tts)
default_models_path = os.path.join(os.environ["LOCALAPPDATA"], "tts")
models_file = os.path.join(default_models_path, "models.json")

# Initialize manager
manager = None
model_refs = {}   # display_name -> model_reference (remote id or local path)
all_models = {}

# TTS instance cache (to avoid reloading same models)
tts_cache = {}  # model_name -> TTS instance

# TTS instance (initialized later)
current_tts = None

# Global dictionary to store models and their voices
tts_models = {}  # { "model_name": ["voice1", "voice2", ...] }   display_name -> ["default"] or list of speakers

def verify_model_files(model_path):
    """Verify that required model files exist and are valid in the given path"""
    if not os.path.exists(model_path):
        return False
    
    try:
        files_in_dir = os.listdir(model_path)
        
        # Check for config.json and verify it's valid JSON
        config_files = [f for f in files_in_dir if f == 'config.json']
        if not config_files:
            return False
        
        config_path = os.path.join(model_path, 'config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                json.load(f)  # This will raise an exception if JSON is invalid
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"Invalid config.json in {model_path}")
            return False
        
        # Check for model files
        model_files = [f for f in files_in_dir if f.endswith('.pth') or f.endswith('.pt')]
        if len(model_files) == 0:
            return False
        
        # Verify model files aren't empty
        for model_file in model_files:
            model_file_path = os.path.join(model_path, model_file)
            if os.path.getsize(model_file_path) == 0:
                print(f"Empty model file: {model_file_path}")
                return False
        
        return True
        
    except Exception as e:
        print(f"Error verifying model files in {model_path}: {e}")
        return False

def test_model_loading(model_name):
    """Test if a model can be loaded successfully"""
    try:
        print(f"Testing model: {model_name}")
        test_tts = TTS(model_name)
        speakers = getattr(test_tts, "speakers", None) or ["default"]
        print(f"✓ Model {model_name} loaded successfully with {len(speakers)} speakers")
        del test_tts  # Clean up
        return True, speakers
    except Exception as e:
        print(f"✗ Model {model_name} failed to load: {e}")
        return False, ["default"]
def get_working_models():
    """Get list of models that actually have valid files on disk and can be loaded"""
    working_models = []
    
    if not os.path.exists(default_models_path):
        print(f"TTS models directory not found: {default_models_path}")
        return working_models
    
    try:
        # First, try some common reliable models that are likely to work
        reliable_models = [
            "tts_models/en/ljspeech/tacotron2-DDC",
            "tts_models/en/ljspeech/vits",
            "tts_models/en/vctk/vits",
            "tts_models/multilingual/multi-dataset/xtts_v2"
        ]
        
        print("Testing reliable models first...")
        for model_name in reliable_models:
            success, speakers = test_model_loading(model_name)
            if success:
                working_models.append((model_name, speakers))
        
        if working_models:
            print(f"Found {len(working_models)} working reliable models")
            return working_models
        
        # If no reliable models work, scan the directory for any working models
        print("No reliable models found, scanning directory...")
        entries = os.listdir(default_models_path)
        found = []
        
        for e in entries:
            item_path = os.path.join(default_models_path, e)
            if os.path.isdir(item_path) and e != "models.json":
                # Convert folder name to model name format
                model_name = e.replace("--", "/")
                
                # Verify the model has required files
                if verify_model_files(item_path):
                    # Test if the model actually loads
                    success, speakers = test_model_loading(model_name)
                    if success:
                        found.append((model_name, speakers))
                    else:
                        print(f"Model {model_name} has files but fails to load")
                else:
                    print(f"Model {model_name} missing required files")
        
        working_models.extend(found)
    
    except Exception as e:
        print(f"Error scanning models directory: {e}")
    
    return working_models

def initialize_tts(eager=False):
    """
    Initialize TTS model registry with better error handling and model verification.
    """
    global manager, model_refs, tts_models

    if not TTS_AVAILABLE:
        print("TTS not available; skipping initialize_tts()")
        return

    models_dir = default_models_path
    os.makedirs(models_dir, exist_ok=True)

    print(f"Looking for TTS models in: {models_dir}")

    # Get list of models that actually work on disk
    working_models = get_working_models()
    print(f"Found {len(working_models)} working models on disk")

    # Initialize with working models
    model_refs = {}
    tts_models = {}
    
    for model_name, speakers in working_models:
        model_refs[model_name] = model_name  # Use the model name as reference
        tts_models[model_name] = speakers
        print(f"Registered model: {model_name} with speakers: {speakers}")

    if not tts_models:
        print("Warning: No working TTS models found!")
        print("You may need to download models using: tts --list_models")
        print("Then download a model like: tts --model_name tts_models/en/ljspeech/tacotron2-DDC --text 'test'")
        return

    # Try to use ModelManager as backup for model discovery (but don't rely on it)
    try:
        print("Attempting to initialize ModelManager for additional model discovery...")
        temp_manager = ModelManager()
        manager = temp_manager
        print("ModelManager initialized successfully")
        
    except Exception as e:
        print(f"ModelManager initialization failed: {e}")
        print("Continuing with locally discovered models only")

    print(f"TTS initialization complete. Total working models: {len(model_refs)}")

def get_model_ref(model_name):
    """Return the model reference (local path or remote id) to pass to TTS()."""
    return model_refs.get(model_name, model_name)

def get_speakers_for_model(model_name):
    """
    Return list of speakers for a model. Handle special cases like XTTS v2.
    """
    global tts_models, tts_cache
    
    if model_name not in tts_models:
        return ["default"]
    
    existing = tts_models.get(model_name)
    if existing and not (len(existing) == 1 and existing[0] == "default"):
        return existing
    
    # Try to get speakers by loading the model
    try:
        if model_name in tts_cache:
            tts_instance = tts_cache[model_name]
        else:
            print(f"Loading model {model_name} to discover speakers...")
            tts_instance = TTS(model_name)
            tts_cache[model_name] = tts_instance
        
        # Handle XTTS v2 specially - it has predefined speakers
        if "xtts" in model_name.lower():
            # XTTS v2 has these built-in speakers
            speakers = [
                "Claribel Dervla", "Daisy Studious", "Gracie Wise", "Tammie Ema",
                "Alison Dietlinde", "Ana Florence", "Annmarie Nele", "Asya Anara",
                "Brenda Stern", "Gitta Nikolina", "Henriette Usha", "Sofia Hellen",
                "Tammy Grit", "Tanja Adelina", "Vjollca Johnnie", "Andrew Chipper",
                "Badr Odhiambo", "Dionisio Schuyler", "Royston Min", "Viktor Eka",
                "Abrahan Mack", "Adde Michal", "Baldur Sanjin", "Craig Gutsy",
                "Damien Black", "Gilberto Mathias", "Ilkin Urbano", "Kazuhiko Atallah",
                "Ludvig Milivoj", "Suad Qasim", "Torcull Diarmuid", "Viktor Menelaos",
                "Xavier Hayden"
            ]
            tts_models[model_name] = speakers
            print(f"Using predefined XTTS speakers: {len(speakers)} available")
            return speakers
        
        # For other models, try to get speakers normally
        speakers = getattr(tts_instance, "speakers", None)
        if speakers and isinstance(speakers, list) and len(speakers) > 0:
            # Filter out None or empty speakers
            speakers = [s for s in speakers if s and str(s).strip()]
            if speakers:
                tts_models[model_name] = speakers
                print(f"Discovered {len(speakers)} speakers for {model_name}")
                return speakers
        
        # Check if model has speaker_manager
        if hasattr(tts_instance, 'synthesizer') and hasattr(tts_instance.synthesizer, 'tts_model'):
            tts_model = tts_instance.synthesizer.tts_model
            if hasattr(tts_model, 'speaker_manager') and tts_model.speaker_manager:
                speakers = tts_model.speaker_manager.speaker_names
                if speakers:
                    tts_models[model_name] = speakers
                    print(f"Found speakers via speaker_manager: {speakers}")
                    return speakers
        
        # Fallback - mark as single speaker
        print(f"No speakers found for {model_name}, using default")
        tts_models[model_name] = ["default"]
        return ["default"]
        
    except Exception as e:
        print(f"Could not load {model_name} to discover speakers: {e}")
        return ["default"]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_audio_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS

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

@app.route("/api/voices")
def get_voices():
    """Return all voices for all loaded TTS models."""
    if not tts_models:
        return jsonify(["default"])

    #all_voices = []
    #for model_name, voices in tts_models.items():
    #    all_voices.extend([f"{model_name}:{v}" for v in voices])
        
    all_voices = []
    story_name = request.args.get("storyName")  # optional param
    nicknames = {}

    if story_name:
        story_data = load_story_data(story_name)
        if story_data and "voiceNicknames" in story_data:
            nicknames = story_data["voiceNicknames"]

    for model_name, voices in tts_models.items():
        for v in voices:
            display = f"{model_name}:{v}"
            # If this voice has a nickname, append it
            for nickname, real in nicknames.items():
                if real == display:
                    display = f"{display} [{nickname}]"
                    break
            all_voices.append(display)

    return jsonify(all_voices)

@app.route('/api/insert-paragraph', methods=['POST'])
def insert_paragraph():
    """Insert a new paragraph at a specific position in a story page"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    insert_index = data.get('insertIndex')
    paragraph_text = data.get('paragraphText', '')
    
    if not all([story_name, page_number is not None, insert_index is not None]):
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
    
    # Insert the new paragraph at the specified index
    page['text'].insert(insert_index, paragraph_text)
    
    # Shift audio indices that come after the insertion point
    if 'audio' in page and page['audio']:
        new_audio = {}
        for key, value in page['audio'].items():
            audio_index = int(key)
            if audio_index >= insert_index:
                new_audio[str(audio_index + 1)] = value
            else:
                new_audio[key] = value
        page['audio'] = new_audio
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True, 'insertedIndex': insert_index})

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
                    
                # Ensure audio object exists
                if 'audio' not in page:
                    page['audio'] = {}
        
        return jsonify(story_data)
    else:
        return jsonify({'error': 'Story not found'}), 404

@app.route('/api/tts-models')
def get_tts_models():
    """Get available TTS models"""
    if not TTS_AVAILABLE:
        return jsonify({'models': [], 'error': 'TTS not available'})
    
    return jsonify({'models': list(tts_models.keys())})

@app.route('/api/preview-voice', methods=['POST'])
def preview_voice():
    if not TTS_AVAILABLE:
        return jsonify({'error': 'TTS not available'}), 400
    
    data = request.json
    voice = data.get('voice')
    model_name, speaker = None, None
    
    print("Previewing voice")
    
    if voice and ":" in voice:
        model_name, speaker = voice.split(":", 1)
    else:
        model_name = voice

    try:
        global current_tts
        if current_tts is None or current_tts.model_name != model_name:
            current_tts = TTS(model_name)
            current_tts.model_name = model_name

        preview_folder = os.path.join(AUDIO_FOLDER, "previews")
        os.makedirs(preview_folder, exist_ok=True)
        
        filename = f"preview_{uuid.uuid4().hex[:8]}.wav"
        filepath = os.path.join(preview_folder, filename)

        kwargs = {}
        voices = tts_models.get(model_name, ["default"])
        if speaker and speaker in voices and not (len(voices) == 1 and voices[0] == "default"):
            kwargs["speaker"] = speaker

        current_tts.tts_to_file(text="Hello world", file_path=filepath, **kwargs)

        return jsonify({"url": f"/audio/previews/{filename}"})
    except Exception as e:
        return jsonify({'error': f'Preview generation failed: {str(e)}'}), 500
    
@app.route('/audio/previews/<filename>')
def serve_preview(filename):
    preview_folder = os.path.join(AUDIO_FOLDER, "previews")
    return send_from_directory(preview_folder, filename)

@app.route('/api/generate-tts', methods=['POST'])
def generate_tts():
    """Generate TTS audio for a paragraph"""
    if not TTS_AVAILABLE:
        return jsonify({'error': 'TTS not available'}), 400

    print("Generating TTS")

    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    paragraph_index = data.get('paragraphIndex')
    text = data.get('text', '')
    voice = data.get('voice', None)
    model_name = None
    speaker = None
    
    # Strip nickname if present: "model:speaker [nickname]"
    if voice and "[" in voice:
        voice = voice.split("[", 1)[0].strip()

    # Handle combined "model:speaker" format (fix: you mentioned semicolon but code uses colon)
    if voice and ":" in voice:
        model_name, speaker = voice.split(":", 1)
    else:
        model_name = data.get('model', voice)
    
    speed = float(data.get('speed', 1.0))
    
    print("Model Name:", model_name)
    print("Speaker:", speaker)
    print("Speed:", speed)

    if not all([story_name, page_number is not None, paragraph_index is not None, text]):
        return jsonify({'error': 'Missing required fields'}), 400

    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404

    try:
        # Use cached TTS instance if available, otherwise create new one
        global tts_cache
        
        if model_name not in tts_cache:
            print(f"Loading TTS model: {model_name}")
            
            # Verify model exists in our registry
            if model_name not in tts_models:
                print(f"Model {model_name} not found in registry. Available models: {list(tts_models.keys())}")
                # Fallback to a working model
                working_models = [m for m in tts_models.keys()]
                if working_models:
                    model_name = working_models[0]
                    print(f"Using fallback model: {model_name}")
                else:
                    return jsonify({'error': 'No working TTS models available'}), 500
            
            try:
                tts_instance = TTS(model_name)
                tts_cache[model_name] = tts_instance
                print(f"Successfully loaded model: {model_name}")
            except Exception as model_error:
                print(f"Failed to load model {model_name}: {model_error}")
                # Try fallback to ljspeech model which is usually reliable
                fallback_model = "tts_models/en/ljspeech/tacotron2-DDC"
                try:
                    print(f"Trying fallback model: {fallback_model}")
                    tts_instance = TTS(fallback_model)
                    tts_cache[fallback_model] = tts_instance
                    model_name = fallback_model
                    speaker = None  # Reset speaker for fallback
                    print(f"Successfully loaded fallback model: {fallback_model}")
                except Exception as fallback_error:
                    print(f"Fallback model also failed: {fallback_error}")
                    return jsonify({'error': f'Failed to load any TTS model. Original error: {str(model_error)}'}), 500
        else:
            tts_instance = tts_cache[model_name]

        # Create audio folder
        story_audio_folder = os.path.join(AUDIO_FOLDER, story_name)
        os.makedirs(story_audio_folder, exist_ok=True)

        # Generate unique filename
        audio_filename = f"p{page_number}_{paragraph_index}_{uuid.uuid4().hex[:8]}.wav"
        audio_path = os.path.join(story_audio_folder, audio_filename)

        # Build kwargs safely
        kwargs = {}
        voices = get_speakers_for_model(model_name)

        # Handle XTTS v2 specially
        if "xtts" in model_name.lower():
            # XTTS requires language parameter
            kwargs["language"] = "en"  # Default to English, you might want to make this configurable
            
            # For XTTS, speaker is required if it's multi-speaker
            if speaker and speaker in voices:
                kwargs["speaker"] = speaker
                print(f"Using XTTS speaker: {speaker}")
            elif voices and len(voices) > 1 and "default" not in voices:
                # Use first available speaker if none specified
                kwargs["speaker"] = voices[0]
                print(f"Using first XTTS speaker: {voices[0]}")
            else:
                # This shouldn't happen with XTTS, but fallback
                kwargs["speaker"] = "Claribel Dervla"  # Default XTTS speaker
                print(f"Using fallback XTTS speaker: Claribel Dervla")
        else:
            # Handle other models normally
            if speaker and speaker in voices and speaker != "default":
                kwargs["speaker"] = speaker
                print(f"Using speaker: {speaker}")
            elif len(voices) > 1 and "default" not in voices:
                # If model has multiple speakers but no "default", use first one
                kwargs["speaker"] = voices[0]
                print(f"Using first available speaker: {voices[0]}")

        print(f"Generating TTS with kwargs: {kwargs}")

        # Generate audio
        tts_instance.tts_to_file(
            text=text,
            file_path=audio_path,
            **kwargs
        )
        
        # Apply speed change if needed
        if speed and speed != 1.0:
            try:
                change_speed(audio_path, speed)
                print(f"Applied speed change: {speed}")
            except Exception as speed_error:
                print(f"Warning: Could not apply speed change tp {audio_path}: {speed_error}")

        # Save to story JSON
        page = next((p for p in story_data['pages'] if p.get('page_number') == page_number), None)
        if page:
            if 'audio' not in page:
                page['audio'] = {}
            page['audio'][str(paragraph_index)] = audio_filename
            save_story_data(story_name, story_data)

        print(f"✓ TTS generation successful: {audio_filename}")
        return jsonify({'success': True, 'filename': audio_filename})

    except Exception as e:
        print("❌ TTS generation failed:")
        traceback.print_exc()  # full traceback in console
        return jsonify({'error': f'TTS generation failed: {str(e)}'}), 500

@app.route('/api/save-voice-nickname', methods=['POST'])
def save_voice_nickname():
    """Save or update a voice nickname for a story"""
    data = request.json
    story_name = data.get("storyName")
    nickname = data.get("nickname")
    voice = data.get("voice")  # "model:speaker"
    
    print("Saving nickname")

    if not all([story_name, nickname, voice]):
        return jsonify({"error": "Missing required fields"}), 400

    story_data = load_story_data(story_name)
    if not story_data:
        return jsonify({"error": "Story not found"}), 404

    if "voiceNicknames" not in story_data:
        story_data["voiceNicknames"] = {}

    # Save mapping
    story_data["voiceNicknames"][nickname] = voice
    save_story_data(story_name, story_data)

    return jsonify({"success": True})
    
@app.route('/api/save-recording', methods=['POST'])
def save_recording():
    """Save recorded audio for a paragraph"""
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
    
    file = request.files['audio']
    story_name = request.form.get('storyName')
    page_number = request.form.get('pageNumber')
    paragraph_index = request.form.get('paragraphIndex')
    
    if not all([story_name, page_number, paragraph_index]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        page_number = int(page_number)
        paragraph_index = int(paragraph_index)
    except ValueError:
        return jsonify({'error': 'Invalid page or paragraph number'}), 400
    
    story_data = load_story_data(story_name)
    
    if "voiceNicknames" not in story_data:
        story_data["voiceNicknames"] = {}
    
    if not story_data:
        return jsonify({'error': 'Story not found'}), 404
    
    try:
        # Create audio folder for story
        story_audio_folder = os.path.join(AUDIO_FOLDER, story_name)
        os.makedirs(story_audio_folder, exist_ok=True)
        
        # Generate unique filename
        audio_filename = f"p{page_number}_{paragraph_index}_{uuid.uuid4().hex[:8]}.wav"
        audio_path = os.path.join(story_audio_folder, audio_filename)
        
        # Save the audio file
        file.save(audio_path)
        
        # Update story data
        page = None
        for p in story_data['pages']:
            if p.get('page_number') == page_number:
                page = p
                break
        
        if page:
            if 'audio' not in page:
                page['audio'] = {}
            page['audio'][str(paragraph_index)] = audio_filename
            
            save_story_data(story_name, story_data)
        
        return jsonify({'success': True, 'filename': audio_filename})
        
    except Exception as e:
        return jsonify({'error': f'Failed to save recording: {str(e)}'}), 500
    
def change_speed(audio_path, speed=1.0):
    tmp_path = audio_path + ".tmp.wav"
    subprocess.run([
        "sox", audio_path, tmp_path, "tempo", str(speed)
    ], check=True)
    os.replace(tmp_path, audio_path)

@app.route('/api/delete-audio', methods=['POST'])
def delete_audio():
    """Delete audio file for a paragraph"""
    data = request.json
    story_name = data.get('storyName')
    page_number = data.get('pageNumber')
    paragraph_index = data.get('paragraphIndex')
    
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
    
    audio_dict = page.get('audio', {})
    paragraph_key = str(paragraph_index)
    
    if paragraph_key not in audio_dict:
        return jsonify({'error': 'Audio not found'}), 404
    
    # Get the audio filename
    audio_filename = audio_dict[paragraph_key]
    
    # Delete the physical file
    audio_path = os.path.join(AUDIO_FOLDER, story_name, audio_filename)
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except Exception as e:
            print(f"Error deleting audio file: {e}")
    
    # Remove from story data
    del audio_dict[paragraph_key]
    
    # Save the updated story
    save_story_data(story_name, story_data)
    
    return jsonify({'success': True})

@app.route('/audio/<story_name>/<filename>')
def serve_audio(story_name, filename):
    """Serve audio files"""
    story_audio_folder = os.path.join(AUDIO_FOLDER, story_name)
    file_path = os.path.join(story_audio_folder, filename)
    
    if os.path.exists(file_path):
        return send_from_directory(story_audio_folder, filename)
    else:
        return jsonify({'error': 'Audio file not found'}), 404

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
    print("Make sure your story JSON files are in the 'stories' folder")
    print("Make sure your images are in the 'images/StoryName/' folders")
    
    # Initialize TTS
    if TTS_AVAILABLE:
        print("Initializing TTS models...")
        initialize_tts()
        print("TTS initialization complete")
    else:
        print("TTS functionality disabled - install Coqui TTS with: pip install TTS")
    
    print("Server will be available at http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)