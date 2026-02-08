import asyncio
import requests
import os
import random
import json
import urllib.parse
from datetime import datetime
import google.generativeai as genai
import edge_tts
from moviepy.editor import *
from moviepy.config import change_settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURATION ---
if os.name == 'nt':
    change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})
else:
    # Common path for Linux/GitHub Actions
    change_settings({"IMAGEMAGICK_BINARY": "/usr/bin/convert"})

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# YouTube Secrets
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

OUTPUT_FILENAME = "dark_intel_quiz.mp4"
METADATA_FILENAME = "video_metadata.json"
HISTORY_FILENAME = "history.json"
VIDEO_SIZE = (1080, 1920)

# --- VISUAL STYLES ---
FONT = "Impact" 
FONT_SIZE_QUESTION = 70 
FONT_SIZE_OPTION = 60    
HIGHLIGHT_COLOR = "#00FF00" 
TEXT_COLOR = "white"
STROKE_COLOR = "black" 
STROKE_WIDTH = 2          
THINKING_TIME = 5        

INDIAN_MALE_VOICES = ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural"]

# --- UTILS & HISTORY ---
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

# --- IMAGE GENERATION (POLLINATIONS) ---
def get_pollinations_image(prompt, filename):
    print(f"🎨 Generating AI Image for prompt: {prompt}")
    
    # URL Encode the prompt
    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://gen.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true&model=flux"
    
    # Robust request with Retries
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        # Increased timeout to 60s for high-quality generation
        response = session.get(url, timeout=60)
        if response.status_code == 200 and len(response.content) > 10000:
            with open(filename, 'wb') as f:
                f.write(response.content)
            print("✅ Image generated successfully.")
            return True
        else:
            print(f"⚠️ Pollinations failed. Status: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Image Error: {e}")
    return False

# --- GEMINI CONTENT ---
def get_gemini_content():
    print("🧠 Asking Gemini for a dark facts quiz...")
    genai.configure(api_key=GEMINI_API_KEY)
    history_context = ", ".join(get_past_questions())
    
    model = genai.GenerativeModel('gemini-2.5-flash') # Updated to latest stable flash

    prompt = f"""
    Generate 1 unique, engaging quiz question for a channel called 'Dark Intel'.
    Topics: Dark History, Psychology, Space, or Tech Facts.
    
    EXCLUDE previous: [{history_context}]
    
    Output STRICT JSON only:
    {{
      "question": "Short question?",
      "options": ["A", "B", "C", "D"],
      "correct_index": 0,
      "image_prompt": "Cinematic, dark aesthetic, 9:16 vertical, photorealistic, no text, related to [Topic]",
      "yt_title": "Title #Shorts",
      "yt_desc": "Description with #Shorts #Facts",
      "yt_tags": "dark, facts, tech"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        save_current_question(data['question'])
        with open(METADATA_FILENAME, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

# --- TTS ---
async def generate_tts(text, filename, voice):
    communicate = edge_tts.Communicate(text, voice, rate="+15%")
    await communicate.save(filename)

# --- VIDEO CREATION ---
def create_video(data):
    voice = random.choice(INDIAN_MALE_VOICES)
    img_file = "bg_gen.jpg"
    
    # Image Generation
    has_image = get_pollinations_image(data['image_prompt'], img_file)
    bg_clip = ImageClip(img_file).resize(VIDEO_SIZE) if has_image else ColorClip(VIDEO_SIZE, color=(20, 20, 20))

    # Audio Segments
    segments = [
        ("q", data['question']),
        ("a", f"Option A: {data['options'][0]}"),
        ("b", f"Option B: {data['options'][1]}"),
        ("c", f"Option C: {data['options'][2]}"),
        ("d", f"Option D: {data['options'][3]}"),
        ("reveal", "The correct answer is coming in 5 seconds.")
    ]
    
    async def run_tts():
        tasks = [generate_tts(text, f"temp_{key}.mp3", voice) for key, text in segments]
        await asyncio.gather(*tasks)
    
    asyncio.run(run_tts())

    # Audio Loading & Timing
    audio_clips = [AudioFileClip(f"temp_{key}.mp3") for key, _ in segments]
    durations = [c.duration for c in audio_clips]
    
    t_q = durations[0]
    t_a = t_q + durations[1]
    t_b = t_a + durations[2]
    t_c = t_b + durations[3]
    t_d = t_c + durations[4]
    t_wait = t_d + durations[5]
    t_reveal = t_wait + THINKING_TIME
    total_dur = t_reveal + 2

    # UI Composition
    txt_q = TextClip(data['question'], font=FONT, fontsize=FONT_SIZE_QUESTION, color=TEXT_COLOR, 
                     stroke_color=STROKE_COLOR, stroke_width=2, size=(900, None), method='caption').set_position(('center', 300)).set_duration(total_dur)

    all_clips = [bg_clip.set_duration(total_dur), txt_q]
    y_pos = 850

    for i, opt in enumerate(data['options']):
        start_t = [t_q, t_a, t_b, t_c][i]
        is_correct = (i == data['correct_index'])
        
        # Normal State
        all_clips.append(TextClip(f"{chr(65+i)}: {opt}", font=FONT, fontsize=FONT_SIZE_OPTION, color=TEXT_COLOR, 
                                  size=(850, None), method='caption', align='West').set_position((110, y_pos)).set_start(start_t).set_end(t_reveal))
        # Reveal State (Highlighted)
        all_clips.append(TextClip(f"{chr(65+i)}: {opt}", font=FONT, fontsize=FONT_SIZE_OPTION, color=HIGHLIGHT_COLOR if is_correct else TEXT_COLOR, 
                                  size=(850, None), method='caption', align='West').set_position((110, y_pos)).set_start(t_reveal).set_duration(total_dur - t_reveal))
        y_pos += 180

    # Finalize
    final_audio = concatenate_audioclips(audio_clips + [AudioClip(lambda t: [0,0], duration=THINKING_TIME)])
    final_video = CompositeVideoClip(all_clips, size=VIDEO_SIZE).set_audio(final_audio).set_duration(total_dur)
    
    print("🎬 Rendering...")
    final_video.write_videofile(OUTPUT_FILENAME, fps=24, codec="libx264", threads=4, logger=None)
    
    # Simple Cleanup
    for key, _ in segments: os.remove(f"temp_{key}.mp3")
    if os.path.exists(img_file): os.remove(img_file)

if __name__ == "__main__":
    content = get_gemini_content()
    if content:
        create_video(content)
