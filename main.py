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

# --- CONFIGURATION ---
# 1. API KEY: Reads from Environment Variable (GitHub Secret)
# If running locally without env var, paste key here for testing, but DO NOT commit to GitHub.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

if not GEMINI_API_KEY:
    # Optional fallback for local testing if env var is missing
    print("⚠️ WARNING: GEMINI_API_KEY not found in environment variables.")

# 2. ImageMagick Path (Auto-Detect OS)
if os.name == 'nt':
    # Windows Path
    change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"})
else:
    # Linux (GitHub Actions) - ImageMagick is installed via apt-get, MoviePy finds it auto.
    pass 

OUTPUT_FILENAME = "gemini_flash_quiz.mp4"
METADATA_FILENAME = "video_metadata.json"
VIDEO_SIZE = (1080, 1920)

# Visual Styles
FONT = "Arial-Bold" 
FONT_SIZE_QUESTION = 65 
FONT_SIZE_OPTION = 55
HIGHLIGHT_COLOR = "#00FF00" 
TEXT_COLOR = "white"
STROKE_COLOR = "black" 
STROKE_WIDTH = 4
THINKING_TIME = 5 

# Voices
INDIAN_MALE_VOICES = [
    "en-IN-PrabhatNeural", "en-IN-NeerjaNeural", "hi-IN-MadhurNeural", 
    "bn-IN-BashkarNeural", "ta-IN-ValluvarNeural"
]

# --- GEMINI AI GENERATOR ---
def get_gemini_content():
    """Asks Gemini Flash for content."""
    print("🧠 Asking Gemini Flash for content...")
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
    except:
        model = genai.GenerativeModel('gemini-pro')

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
        text = response.text
        if "```" in text:
            text = text.replace("```json", "").replace("```", "")
        text = text.strip()
        
        data = json.loads(text)
        print(f"✅ Gemini Generated: {data['question']}")
        
        # Save Metadata
        metadata = {
            "title": data['youtube_title'],
            "description": data['youtube_description'],
            "tags": data['youtube_tags']
        }
        with open(METADATA_FILENAME, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)
        print(f"📄 Metadata saved to {METADATA_FILENAME}")
        
        return data
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

# --- ASSET GENERATION ---
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
        response = requests.get(url)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            print("✅ Image saved.")
        else:
            print(f"❌ Error fetching image. Status: {response.status_code}")
    except Exception as e:
        print(f"❌ Connection error: {e}")
    return filename

# --- VIDEO CORE ---
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
        tasks = []
        for key, val in segments.items():
            tasks.append(generate_segment_tts(val['text'], val['file'], selected_voice))
        await asyncio.gather(*tasks)

    print("🎤 Generating audio...")
    asyncio.run(run_all_tts())

    # Timing Logic
    aud_q = AudioFileClip(segments["q"]["file"])
    aud_a = AudioFileClip(segments["a"]["file"])
    aud_b = AudioFileClip(segments["b"]["file"])
    aud_c = AudioFileClip(segments["c"]["file"])
    aud_d = AudioFileClip(segments["d"]["file"])
    aud_outro = AudioFileClip(segments["outro"]["file"])
    
    time_q_end = aud_q.duration
    time_a_start = time_q_end
    time_a_end = time_a_start + aud_a.duration
    time_b_start = time_a_end
    time_b_end = time_b_start + aud_b.duration
    time_c_start = time_b_end
    time_c_end = time_c_start + aud_c.duration
    time_d_start = time_c_end
    time_d_end = time_d_start + aud_d.duration
    time_outro_start = time_d_end
    time_outro_end = time_outro_start + aud_outro.duration
    
    time_reveal = time_outro_end + THINKING_TIME
    total_duration = time_reveal + 3

    # Visuals
    if os.path.exists(img_filename):
        bg_clip = ImageClip(img_filename).resize(VIDEO_SIZE).set_duration(total_duration)
    else:
        bg_clip = ColorClip(size=VIDEO_SIZE, color=(30, 30, 40), duration=total_duration)
    
    txt_q = (TextClip(data['question'], font=FONT, fontsize=FONT_SIZE_QUESTION, 
                      color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH,
                      size=(900, None), method='caption')
             .set_position(('center', 250))
             .set_start(0)
             .set_duration(total_duration))

    option_clips = []
    y_start = 750
    y_gap = 160
    
    def create_option_clip(text, start_time, is_answer, y_pos):
        normal = (TextClip(text, font=FONT, fontsize=FONT_SIZE_OPTION, 
                           color=TEXT_COLOR, stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH,
                           size=(850, None), method='caption', align='West')
                  .set_position(('center', y_pos))
                  .set_start(start_time)
                  .set_end(time_reveal))
        
        reveal = (TextClip(text, font=FONT, fontsize=FONT_SIZE_OPTION, 
                           color=HIGHLIGHT_COLOR if is_answer else TEXT_COLOR, 
                           stroke_color=STROKE_COLOR, stroke_width=STROKE_WIDTH,
                           size=(850, None), method='caption', align='West')
                  .set_position(('center', y_pos))
                  .set_start(time_reveal)
                  .set_duration(total_duration - time_reveal))
        return [normal, reveal]

    option_clips.extend(create_option_clip(f"A: {data['options'][0]}", time_a_start, data['correct_index'] == 0, y_start))
    option_clips.extend(create_option_clip(f"B: {data['options'][1]}", time_b_start, data['correct_index'] == 1, y_start + y_gap))
    option_clips.extend(create_option_clip(f"C: {data['options'][2]}", time_c_start, data['correct_index'] == 2, y_start + (y_gap*2)))
    option_clips.extend(create_option_clip(f"D: {data['options'][3]}", time_d_start, data['correct_index'] == 3, y_start + (y_gap*3)))

    # Composite
    silence_clip = AudioClip(lambda t: [0, 0], duration=THINKING_TIME)
    final_audio = concatenate_audioclips([aud_q, aud_a, aud_b, aud_c, aud_d, aud_outro, silence_clip])
    
    final_video = CompositeVideoClip([bg_clip, txt_q] + option_clips, size=VIDEO_SIZE)
    final_video = final_video.set_audio(final_audio)
    final_video = final_video.set_duration(total_duration)
    
    # Use logger=None to keep terminal clean
    final_video.write_videofile(OUTPUT_FILENAME, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    # Cleanup
    try:
        aud_q.close(); aud_a.close(); aud_b.close(); aud_c.close(); aud_d.close(); aud_outro.close()
        for seg in segments.values():
            if os.path.exists(seg["file"]): os.remove(seg["file"])
        if os.path.exists(img_filename): os.remove(img_filename)
    except:
        pass
    print(f"✨ SUCCESS! Video saved as: {OUTPUT_FILENAME}")
    print(f"📄 Metadata saved as: {METADATA_FILENAME}")

if __name__ == "__main__":
    quiz_data = get_gemini_content()
    if quiz_data:
        create_quiz_video(quiz_data)
