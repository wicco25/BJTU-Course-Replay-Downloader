"""转写模块 - 使用faster-whisper将音频转写为文字，输出TXT+SRT+JSON"""

import os
import json
from config import load_config


class Transcriber:
    """faster-whisper 语音转文字"""

    def __init__(self):
        self.cfg = load_config()
        self._model = None
        self._model_size = None
        self._device = None

    def _load_model(self, model_size=None):
        size = model_size or self.cfg.get("whisper_model", "large-v3-turbo")
        device = self.cfg.get("whisper_device", "auto")

        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"

        if device == "cuda":
            compute_type = "float16"
        elif size.startswith("large"):
            compute_type = "int8"
        else:
            compute_type = "int8"

        if self._model is None or self._model_size != size or self._device != device:
            from faster_whisper import WhisperModel
            print(f"[Transcriber] 加载模型: {size} "
                  f"(device={device}, compute={compute_type})")
            self._model = WhisperModel(
                size, device=device, compute_type=compute_type,
                cpu_threads=4, num_workers=1,
            )
            self._model_size = size
            self._device = device
        return self._model

    def transcribe(self, audio_path, progress_callback=None, model_size=None):
        """转写音频文件，返回带有时间戳的段落列表"""
        model = self._load_model(model_size)
        language = self.cfg.get("whisper_language", "zh")
        if language == "auto":
            language = None

        segments_out = []
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
        )

        total_duration = info.duration
        for segment in segments:
            segments_out.append({
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip(),
            })
            if progress_callback and total_duration > 0:
                progress_callback(min(segment.end / total_duration, 1.0))

        return {
            "language": info.language,
            "duration": round(total_duration, 1),
            "segments": segments_out,
            "full_text": "".join(s["text"] for s in segments_out),
        }

    def transcribe_to_file(self, audio_path, output_path=None,
                           progress_callback=None, model_size=None):
        """转写并保存到文件（输出 TXT + SRT + JSON）

        output_path: JSON 输出路径，TXT/SRT 由此路径派生
        """
        result = self.transcribe(audio_path, progress_callback, model_size)

        if output_path is None:
            output_dir = self.cfg.get("transcript_dir", ".")
            base = os.path.splitext(os.path.basename(audio_path))[0]
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, base + "_transcript.json")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        base_path = output_path.replace("_transcript.json", "")

        # JSON（供总结等后续处理）
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # TXT（纯文本，每句一行，对齐 whisper.py）
        txt_path = base_path + ".txt"
        with open(txt_path, "w", encoding="utf-8") as f_txt:
            for seg in result["segments"]:
                f_txt.write(seg["text"] + "\n")

        # SRT（标准字幕格式，对齐 whisper.py）
        srt_path = base_path + ".srt"
        with open(srt_path, "w", encoding="utf-8") as f_srt:
            for i, seg in enumerate(result["segments"], start=1):
                f_srt.write(f"{i}\n")
                f_srt.write(f"{self._fmt_srt(seg['start'])} --> {self._fmt_srt(seg['end'])}\n")
                f_srt.write(f"{seg['text']}\n\n")

        return result, output_path

    @staticmethod
    def _fmt_srt(seconds):
        """秒数 → SRT 时间格式 HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
