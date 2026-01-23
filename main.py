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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# YouTube Secrets
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

if os.name == 'nt':
    change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})

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
STROKE_WIDTH = 1         
THINKING_TIME = 3       

# Voices
INDIAN_MALE_VOICES = [
    "en-IN-PrabhatNeural", "en-IN-NeerjaNeural"
]

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

# --- SMART SCHEDULER (NEW) ---
def get_scheduled_time():
    """Calculates the next best slot (8:30 AM or 9:30 PM IST)."""
    # Define India Standard Time (IST)
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_offset)
    
    # Define Targets
    today_morning = now.replace(hour=8, minute=30, second=0, microsecond=0)
    today_evening = now.replace(hour=21, minute=30, second=0, microsecond=0)
    
    if now < today_morning:
        # Before 8:30 AM -> Schedule for Morning
        target = today_morning
        label = "Today Morning (8:30 AM)"
    elif now < today_evening:
        # Between 8:30 AM and 9:30 PM -> Schedule for Night
        target = today_evening
        label = "Today Night (9:30 PM)"
    else:
        # After 9:30 PM -> Schedule for Tomorrow Morning
        target = today_morning + timedelta(days=1)
        label = "Tomorrow Morning (8:30 AM)"
        
    return target.isoformat(), label

# --- YOUTUBE UPLOADER ---
def upload_to_youtube(video_path, metadata_path):
    print("🚀 Starting YouTube Upload...")
    
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        print("❌ Upload Skipped: Missing YouTube Secrets.")
        return

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Calculate Schedule Time
    # publish_at, schedule_label = get_scheduled_time()
    print(f"⏰ Smart Schedule: {schedule_label}")

    creds = Credentials(None, refresh_token=YT_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=YT_CLIENT_ID, client_secret=YT_CLIENT_SECRET)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"].split(","),
            "categoryId": "27" 
        },
        "status": {
            "privacyStatus": "private",  # Must be private to use publishAt
           # "publishAt": publish_at,
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

    print(f"✅ Upload Complete! Video scheduled for {schedule_label}")

# --- GEMINI CONTENT ---
def get_gemini_content():
    print("🧠 Asking Gemini Flash for content...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    history_context = ", ".join(get_past_questions())
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
    except:
        model = genai.GenerativeModel('gemini-2.0-flash')

    prompt = f"""
    Generate 1 unique, engaging General Knowledge/Trivia question for Indian students.
    Topics:  Science,coding,computers,electronics,ai, or Tech.
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
      "image_prompt": "Cinematic 9:16 background description, no text.",
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
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(filename)
    return filename

def get_pollinations_image(prompt, filename):
    print(f"🎨 Requesting Image...")
    clean_prompt = prompt.replace("\n", " ")
    encoded_prompt = urllib.parse.quote(clean_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    
    try:
        with open(filename, 'wb') as f:
            f.write(requests.get(url).content)
        print("✅ Image saved.")
    except: 
        pass
    return filename

def create_quiz_video(data):
    selected_voice = random.choice(INDIAN_MALE_VOICES)
    print(f"🎙️ Using Voice: {selected_voice}")

    img_filename = "temp_bg.jpg"
    get_pollinations_image(data['image_prompt'], img_filename)

    segments = {
        "q":   {"text": data['question'], "file": "temp_q.mp3"},
        "a":   {"text": f"Option A... {data['options'][0]}", "file": "temp_a.mp3"},
        "b":   {"text": f"Option B... {data['options'][1]}", "file": "temp_b.mp3"},
        "c":   {"text": f"Option C... {data['options'][2]}", "file": "temp_c.mp3"},
        "d":   {"text": f"Option D... {data['options'][3]}", "file": "temp_d.mp3"},
        "outro": {"text": "Wait for the correct answer or check the comments.", "file": "temp_outro.mp3"}
    }

    async def run_all_tts():
        tasks = [generate_segment_tts(val['text'], val['file'], selected_voice) for val in segments.values()]
        await asyncio.gather(*tasks)
    asyncio.run(run_all_tts())

    aud_q = AudioFileClip(segments["q"]["file"])
    aud_a = AudioFileClip(segments["a"]["file"])
    aud_b = AudioFileClip(segments["b"]["file"])
    aud_c = AudioFileClip(segments["c"]["file"])
    aud_d = AudioFileClip(segments["d"]["file"])
    aud_outro = AudioFileClip(segments["outro"]["file"])
    
    t_q = aud_q.duration
    t_a = t_q + aud_a.duration
    t_b = t_a + aud_b.duration
    t_c = t_b + aud_c.duration
    t_d = t_c + aud_d.duration
    t_out = t_d + aud_outro.duration
    t_reveal = t_out + THINKING_TIME
    total_dur = t_reveal + 3
    
    bg_clip = ImageClip(img_filename).resize(VIDEO_SIZE).set_duration(total_dur) if os.path.exists(img_filename) else ColorClip(VIDEO_SIZE, (30,30,30), duration=total_dur)
    
    txt_q = TextClip(data['question'], font=FONT, fontsize=FONT_SIZE_QUESTION, color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(950, None), method='caption').set_position(('center', 250)).set_start(0).set_duration(total_dur)

    clips = [bg_clip, txt_q]
    y_start, y_gap = 800, 180
    
    def make_opt(txt, t_start, correct, y):
        n = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(900,None), method='caption', align='West').set_position(('center', y)).set_start(t_start).set_end(t_reveal)
        r = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=HIGHLIGHT_COLOR if correct else TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(900,None), method='caption', align='West').set_position(('center', y)).set_start(t_reveal).set_duration(total_dur - t_reveal)
        return [n, r]

    clips += make_opt(f"A: {data['options'][0]}", t_q, data['correct_index']==0, y_start)
    clips += make_opt(f"B: {data['options'][1]}", t_a, data['correct_index']==1, y_start+y_gap)
    clips += make_opt(f"C: {data['options'][2]}", t_b, data['correct_index']==2, y_start+y_gap*2)
    clips += make_opt(f"D: {data['options'][3]}", t_c, data['correct_index']==3, y_start+y_gap*3)
    
    silence = AudioClip(lambda t: [0,0], duration=THINKING_TIME)
    final_audio = concatenate_audioclips([aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro, silence])
    
    final = CompositeVideoClip(clips, size=VIDEO_SIZE).set_audio(final_audio).set_duration(total_dur)
    final.write_videofile(OUTPUT_FILENAME, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    try:
        [c.close() for c in [aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro]]
        [os.remove(f) for f in [img_filename] + [s['file'] for s in segments.values()] if os.path.exists(f)]
    except: pass
    
    print(f"✨ Video Generated: {OUTPUT_FILENAME}")
    upload_to_youtube(OUTPUT_FILENAME, METADATA_FILENAME)

if __name__ == "__main__":
    d = get_gemini_content()
    if d: create_quiz_video(d)
