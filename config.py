"""配置管理模块"""
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG = {
    "base_url": "http://123.121.147.7:88/ve",
    "cookie_file": os.path.join(BASE_DIR, "cookies.txt"),
    "download_dir": os.path.join(BASE_DIR, "downloads"),
    "audio_dir": os.path.join(BASE_DIR, "audio"),
    "transcript_dir": os.path.join(BASE_DIR, "transcripts"),
    "srt_dir": os.path.join(BASE_DIR, "subtitles"),
    "summary_dir": os.path.join(BASE_DIR, "summaries"),
    "session_id": "",
    "api_key": "",
    "api_base_url": "https://api.openai.com/v1",
    "api_model": "gpt-4o",
    "whisper_model": "large-v3-turbo",
    "whisper_device": "auto",
    "whisper_language": "zh",
    "fast_download_progress": True,
    "parallel_hls_download": True,
    "use_ytdlp": True,
    "segment_workers": 16,
    "segment_retries": 3,
    "stream_prefetch_workers": 4,
    "download_workers": 2,
    "download_video_format": True,
    "download_audio_format": False,
    "auto_relogin": True,
}

CONFIG_FILE = os.path.join(BASE_DIR, "settings.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            cfg = {**DEFAULT_CONFIG, **saved}
    else:
        cfg = dict(DEFAULT_CONFIG)
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_download_path(course_name, filename=""):
    cfg = load_config()
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in course_name)
    folder = os.path.join(cfg["download_dir"], safe_name)
    os.makedirs(folder, exist_ok=True)
    if filename:
        return os.path.join(folder, filename)
    return folder
