from faster_whisper import WhisperModel
import os

# 1. 设置音视频文件路径
audio_file = "419.m4a"
# 自动根据音频名字生成 txt 和 srt 的文件名
base_name = os.path.splitext(audio_file)[0]
txt_file = f"{base_name}.txt"
srt_file = f"{base_name}.srt"

# 2. 辅助函数：把秒数转换成 SRT 字幕需要的标准时间格式 (00:00:00,000)
def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

# 3. 加载 large-v3 模型并开启 int8 量化
print("正在加载模型...")
model = WhisperModel("large-v3", device="cuda", compute_type="int8")

# 4. 开始识别
print(f"正在识别音频：{audio_file} ...")
segments, info = model.transcribe(audio_file, beam_size=5, language="zh")

# 5. 同步写入 txt 和 srt 文件
print("正在导出文件...")
# 同时打开两个文件准备写入
with open(txt_file, "w", encoding="utf-8") as f_txt, \
     open(srt_file, "w", encoding="utf-8") as f_srt:
    
    # 遍历识别出的一句句话
    for i, segment in enumerate(segments, start=1):
        text = segment.text.strip() # 去掉前后多余的空格
        
        # --- 打印在屏幕上看看进度 ---
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {text}")
        
        # --- 写入 TXT（纯文本，每句话占一行） ---
        f_txt.write(text + "\n")
        
        # --- 写入 SRT（标准字幕格式） ---
        start_time = format_time(segment.start)
        end_time = format_time(segment.end)
        f_srt.write(f"{i}\n")                     # 第几句
        f_srt.write(f"{start_time} --> {end_time}\n") # 时间轴
        f_srt.write(f"{text}\n\n")                # 字幕内容

print(f"✅ 处理完成！已成功导出：\n1. {txt_file}\n2. {srt_file}")