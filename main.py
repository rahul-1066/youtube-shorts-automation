import asyncio
import requests
import os
import random
import json
import urllib.parse
import google.generativeai as genai
import edge_tts
from moviepy.editor import *
from moviepy.config import change_settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# YouTube Secrets (Read from Env)
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

if os.name == 'nt':
    change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})

OUTPUT_FILENAME = "gemini_flash_quiz.mp4"
METADATA_FILENAME = "video_metadata.json"
VIDEO_SIZE = (1080, 1920)

# Styles & Voices
FONT = "Impact" 
FONT_SIZE_QUESTION = 70 
FONT_SIZE_OPTION = 60
HIGHLIGHT_COLOR = "#00FF00" 
TEXT_COLOR = "white"
STROKE_COLOR = "black" 
STROKE_WIDTH = 1
THINKING_TIME = 4 
INDIAN_MALE_VOICES = ["en-IN-PrabhatNeural", "en-IN-NeerjaNeural"]

# --- YOUTUBE UPLOADER ---
def upload_to_youtube(video_path, metadata_path):
    """Uploads the video to YouTube using the stored Refresh Token."""
    print("🚀 Starting YouTube Upload...")
    
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        print("❌ Upload Skipped: Missing YouTube API Secrets.")
        return

    # Load Metadata
    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 1. Authenticate using Refresh Token (No browser needed)
    creds = Credentials(
        None, # No access token yet
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )

    youtube = build("youtube", "v3", credentials=creds)

    # 2. Prepare Request
    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"].split(","),
            "categoryId": "27" # Education
        },
        "status": {
            "privacyStatus": "private", # Change to 'private' if you want to review first
            "selfDeclaredMadeForKids": False
        }
    }

    # 3. Upload
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"   Uploading... {int(status.progress() * 100)}%")

    print(f"✅ Upload Complete! Video ID: {response.get('id')}")

# --- CONTENT GENERATION ---
def get_gemini_content():
    print("🧠 Asking Gemini Flash for content...")
    genai.configure(api_key=GEMINI_API_KEY)
    try:
       model = genai.GenerativeModel('gemini-2.5-flash')
    except:
        model = genai.GenerativeModel('gemini-2.0-flash')

    prompt = """
    Generate 1 unique, engaging General Knowledge or Trivia question suitable for an Indian audience (UPSC/Student level).
    Topics can be History, Science, Indian Polity, Geography, or Tech.
    Make the question small (up to 8 words only).
    
    ALSO generate YouTube Video Metadata.
    
    Output STRICT JSON format ONLY. Do not use Markdown.
    Structure:
    {
      "id": 1,
      "question": "The question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_index": 0, 
      "image_prompt": "A highly detailed, cinematic, vertical 9:16 description of the background image related to the question. Do not include text in the image.",
      "youtube_title": "A catchy, viral 5-8 word title for YouTube Shorts #Shorts",
      "youtube_description": "A 2-sentence engaging description including the question. Add 3-4 hashtags.",
      "youtube_tags": "tag1, tag2, tag3, tag4, tag5"
    }
    """
    try:
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        
        metadata = {
            "title": data['youtube_title'],
            "description": data['youtube_description'],
            "tags": data['youtube_tags']
        }
        with open(METADATA_FILENAME, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
        return data
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

async def generate_segment_tts(text, filename, voice, rate="+20%"):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(filename)
    return filename

def get_pollinations_image(prompt, filename):
    clean_prompt = prompt.replace("\n", " ")
    encoded_prompt = urllib.parse.quote(clean_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true"
    try:
        with open(filename, 'wb') as f:
            f.write(requests.get(url).content)
    except: pass
    return filename

def create_quiz_video(data):
    selected_voice = random.choice(INDIAN_MALE_VOICES)
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

    # Build Clips
    aud_q = AudioFileClip(segments["q"]["file"])
    aud_a = AudioFileClip(segments["a"]["file"])
    aud_b = AudioFileClip(segments["b"]["file"])
    aud_c = AudioFileClip(segments["c"]["file"])
    aud_d = AudioFileClip(segments["d"]["file"])
    aud_outro = AudioFileClip(segments["outro"]["file"])
    
    # Calc Timings
    t_q = aud_q.duration
    t_a = t_q + aud_a.duration
    t_b = t_a + aud_b.duration
    t_c = t_b + aud_c.duration
    t_d = t_c + aud_d.duration
    t_out = t_d + aud_outro.duration
    t_reveal = t_out + THINKING_TIME
    total_dur = t_reveal + 3
    
    bg_clip = ImageClip(img_filename).resize(VIDEO_SIZE).set_duration(total_dur) if os.path.exists(img_filename) else ColorClip(VIDEO_SIZE, (30,30,30), duration=total_dur)
    
    txt_q = TextClip(data['question'], font=FONT, fontsize=FONT_SIZE_QUESTION, color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(900,None), method='caption').set_position(('center', 250)).set_start(0).set_duration(total_dur)
    
    clips = [bg_clip, txt_q]
    y_start, y_gap = 750, 160
    
    def make_opt(txt, t_start, correct, y):
        n = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(850,None), method='caption', align='West').set_position(('center', y)).set_start(t_start).set_end(t_reveal)
        r = TextClip(txt, font=FONT, fontsize=FONT_SIZE_OPTION, color=HIGHLIGHT_COLOR if correct else TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH, size=(850,None), method='caption', align='West').set_position(('center', y)).set_start(t_reveal).set_duration(total_dur - t_reveal)
        return [n, r]

    clips += make_opt(f"A: {data['options'][0]}", t_q, data['correct_index']==0, y_start)
    clips += make_opt(f"B: {data['options'][1]}", t_a, data['correct_index']==1, y_start+y_gap)
    clips += make_opt(f"C: {data['options'][2]}", t_b, data['correct_index']==2, y_start+y_gap*2)
    clips += make_opt(f"D: {data['options'][3]}", t_c, data['correct_index']==3, y_start+y_gap*3)
    
    silence = AudioClip(lambda t: [0,0], duration=THINKING_TIME)
    final_audio = concatenate_audioclips([aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro, silence])
    
    final = CompositeVideoClip(clips, size=VIDEO_SIZE).set_audio(final_audio).set_duration(total_dur)
    final.write_videofile(OUTPUT_FILENAME, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    # Cleanup
    try:
        [c.close() for c in [aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro]]
        [os.remove(f) for f in [img_filename] + [s['file'] for s in segments.values()] if os.path.exists(f)]
    except: pass
    
    print(f"✨ Video Generated: {OUTPUT_FILENAME}")
    
    # --- TRIGGER UPLOAD ---
    upload_to_youtube(OUTPUT_FILENAME, METADATA_FILENAME)

if __name__ == "__main__":
    d = get_gemini_content()
    if d: create_quiz_video(d)
