import asyncio
import requests
import os
import random
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
import google.generativeai as genai
import edge_tts
from moviepy.editor import *
from moviepy.config import change_settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- CONFIGURATION ---
if os.name == 'nt':
    change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})
else:
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# YouTube Secrets
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

OUTPUT_FILENAME = "gemini_flash_quiz.mp4"
METADATA_FILENAME = "video_metadata.json"
HISTORY_FILENAME = "history.json"
VIDEO_SIZE = (1080, 1920)

# --- VISUAL STYLES ---
FONT = "Impact" 
FONT_SIZE_QUESTION = 75 
FONT_SIZE_OPTION = 60    
HIGHLIGHT_COLOR = "#00FF00" 
TEXT_COLOR = "white"
STROKE_COLOR = "black" 
STROKE_WIDTH = 2          
THINKING_TIME = 3        

# Voices
INDIAN_MALE_VOICES = ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural"]

# --- HISTORY MANAGER ---
def get_past_questions():
    if os.path.exists(HISTORY_FILENAME):
        try:
            with open(HISTORY_FILENAME, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return []
    return []

def save_current_question(question_text):
    history = get_past_questions()
    history.append(question_text)
    if len(history) > 50: history = history[-50:]
    with open(HISTORY_FILENAME, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)

# --- YOUTUBE UPLOADER ---
def upload_to_youtube(video_path, metadata_path):
    print("🚀 Starting YouTube Upload...")
    
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        print("❌ Upload Skipped: Missing YouTube Secrets.")
        return

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    creds = Credentials(None, refresh_token=YT_REFRESH_TOKEN, 
                        token_uri="https://oauth2.googleapis.com/token", 
                        client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"].split(","),
            "categoryId": "27" 
        },
        "status": {
            "privacyStatus": "private", 
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    print("   Uploading...")
    while response is None:
        status, response = request.next_chunk()
        if status: print(f"   Progress: {int(status.progress() * 100)}%")

    print("✅ Upload Complete!")

# --- GEMINI CONTENT ---
def get_gemini_content():
    print("🧠 Asking Gemini Flash for content...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    history_context = ", ".join(get_past_questions())
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
    except:
        model = genai.GenerativeModel('gemini-pro')

    prompt = f"""
    Generate 1 unique, engaging General Knowledge/Trivia question for Indian students.
    Topics: Science, coding, computers, electronics, AI, or Tech.
    Question length: Small (max 8 words).
    
    EXCLUDE these previous questions: [{history_context}]
    
    ALSO generate YouTube Metadata.
    Output STRICT JSON. No Markdown.
    Structure:
    {{
      "id": 1,
      "question": "Question text?",
      "options": ["A", "B", "C", "D"],
      "correct_index": 0, 
      "image_prompt": "9:16 background description, no text.",
      "youtube_title": "Viral 5-8 word title #Shorts",
      "youtube_description": "2-sentence description with hashtags.",
      "youtube_tags": "tag1, tag2, tag3"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        print(f"✅ Gemini Generated: {data['question']}")
        
        save_current_question(data['question'])
        
        with open(METADATA_FILENAME, "w", encoding="utf-8") as f:
            json.dump({
                "title": data['youtube_title'],
                "description": data['youtube_description'],
                "tags": data['youtube_tags']
            }, f, indent=4)
        
        return data
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

# --- ASSETS & VIDEO ---
async def generate_segment_tts(text, filename, voice, rate="+20%"):
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(filename)
    except Exception as e:
        print(f"⚠️ TTS Error for {filename}: {e}")



def get_pollinations_image(prompt, filename):
    print(f"🎨 Requesting Image...")
    clean_prompt = urllib.parse.quote(prompt.replace("\n", " "))
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1080&nologo=true&model=flux&key=sk_ezYiRxPA927wb2dN8Gia94UBmfrxvNJX"
    
    # Setup Retry Strategy
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        # Increase timeout to 60s for flux model generation
        response = session.get(url, timeout=60)
        
        if response.status_code == 200 and len(response.content) > 5000: # Valid images are usually > 5KB
            with open(filename, 'wb') as f:
                f.write(response.content)
            print("✅ Image saved.")
            return True
        else:
            print(f"⚠️ Image Download Failed (Status: {response.status_code})")
    except Exception as e: 
        print(f"⚠️ Image Connection Error: {e}")
    return False

def create_quiz_video(data):
    selected_voice = random.choice(INDIAN_MALE_VOICES)
    print(f"🎙️ Using Voice: {selected_voice}")

    img_filename = "temp_bg.jpg"
    image_downloaded = get_pollinations_image(data['image_prompt'], img_filename)

    # --- CRITICAL FIX: SAFETY FALLBACK ---
    # If image failed to download, use a dark grey color background instead of crashing
    if image_downloaded and os.path.exists(img_filename):
        # Ensure 'bg_clip' is initialized here
        bg_clip_source = ImageClip(img_filename).resize(VIDEO_SIZE)
    else:
        print("⚠️ Using Fallback Color Background (Image failed)")
        bg_clip_source = ColorClip(VIDEO_SIZE, color=(30, 30, 30))

    segments = {
        "q":   {"text": data['question'], "file": "temp_q.mp3"},
        "a":   {"text": f"Option A... {data['options'][0]}", "file": "temp_a.mp3"},
        "b":   {"text": f"Option B... {data['options'][1]}", "file": "temp_b.mp3"},
        "c":   {"text": f"Option C... {data['options'][2]}", "file": "temp_c.mp3"},
        "d":   {"text": f"Option D... {data['options'][3]}", "file": "temp_d.mp3"},
        "outro": {"text": "Wait for the correct answer or check the comments.", "file": "temp_outro.mp3"}
    }

    # Parallel TTS generation
    async def run_all_tts():
        tasks = [generate_segment_tts(val['text'], val['file'], selected_voice) for val in segments.values()]
        await asyncio.gather(*tasks)
    asyncio.run(run_all_tts())

    # Load Audio
    try:
        aud_q = AudioFileClip(segments["q"]["file"])
        aud_a = AudioFileClip(segments["a"]["file"])
        aud_b = AudioFileClip(segments["b"]["file"])
        aud_c = AudioFileClip(segments["c"]["file"])
        aud_d = AudioFileClip(segments["d"]["file"])
        aud_outro = AudioFileClip(segments["outro"]["file"])
        audio_clips = [aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro]
    except OSError:
        print("❌ Critical TTS Failure. Exiting.")
        return

    # Timing
    t_q = aud_q.duration
    t_a = t_q + aud_a.duration
    t_b = t_a + aud_b.duration
    t_c = t_b + aud_c.duration
    t_d = t_c + aud_d.duration
    t_out = t_d + aud_outro.duration
    t_reveal = t_out + THINKING_TIME
    total_dur = t_reveal + 3
    
    # Set background duration
    bg_clip = bg_clip_source.set_duration(total_dur)
    
    # Text Clips
    txt_q = TextClip(data['question'], font=FONT, fontsize=FONT_SIZE_QUESTION, color=TEXT_COLOR, 
                     stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(950, None), 
                     method='caption').set_position(('center', 250)).set_start(0).set_duration(total_dur)

    clips = [bg_clip, txt_q]
    y_start, y_gap = 800, 180
    
    def make_opt(txt, t_start, correct, y):
        n = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=TEXT_COLOR, 
                     stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(900,None), 
                     method='caption', align='West').set_position(('center', y)).set_start(t_start).set_end(t_reveal)
        
        r = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=HIGHLIGHT_COLOR if correct else TEXT_COLOR, 
                     stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(900,None), 
                     method='caption', align='West').set_position(('center', y)).set_start(t_reveal).set_duration(total_dur - t_reveal)
        return [n, r]

    clips += make_opt(f"A: {data['options'][0]}", t_q, data['correct_index']==0, y_start)
    clips += make_opt(f"B: {data['options'][1]}", t_a, data['correct_index']==1, y_start+y_gap)
    clips += make_opt(f"C: {data['options'][2]}", t_b, data['correct_index']==2, y_start+y_gap*2)
    clips += make_opt(f"D: {data['options'][3]}", t_c, data['correct_index']==3, y_start+y_gap*3)
    
    silence = AudioClip(lambda t: [0,0], duration=THINKING_TIME)
    final_audio = concatenate_audioclips(audio_clips + [silence])
    
    final = CompositeVideoClip(clips, size=VIDEO_SIZE).set_audio(final_audio).set_duration(total_dur)
    
    print("🎬 Rendering Video...")
    final.write_videofile(
        OUTPUT_FILENAME, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac", 
        logger=None, 
        preset='ultrafast', 
        threads=4
    )
    
    # Cleanup
    try:
        final.close()
        for c in audio_clips: c.close()
        files_to_remove = [img_filename] + [s['file'] for s in segments.values()]
        for f in files_to_remove:
            if os.path.exists(f): os.remove(f)
    except: pass
    
    print(f"✨ Video Generated: {OUTPUT_FILENAME}")
    upload_to_youtube(OUTPUT_FILENAME, METADATA_FILENAME)

if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is missing.")
    else:
        d = get_gemini_content()
        if d: create_quiz_video(d)
