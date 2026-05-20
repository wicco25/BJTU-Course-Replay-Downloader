# 课程回放下载工具

一个面向课程回放平台的本地工具，用于获取课程列表、选择回放、下载视频或音频，并可继续进行语音转写和课程内容总结。项目提供 PyQt5 图形界面、命令行交互模式，以及独立的 BJTU CAS 登录 Cookie 获取脚本。

> 说明：请仅用于你有权限访问的课程资源。本工具不会绕过平台权限，所有课程、回放和视频流信息都依赖有效登录态和平台接口返回。

## 功能概览

- 获取学期列表、课程列表和课程回放列表。
- 支持选择回放画面下载，包括课件画面、教师画面、学生画面等。
- 支持批量下载视频或仅下载音频。
- 支持 HLS/m3u8 下载，底层使用 `ffmpeg` 合并或抽取媒体流。
- 支持使用 `faster-whisper` 将音频转写为 `JSON`、`TXT`、`SRT`。
- 支持调用 OpenAI 兼容接口生成课程总结。
- 提供独立 CAS 登录脚本，可识别验证码并导出 Cookie。
- GUI 内置多项性能优化：缓存课程数据、并发预取流信息、有限并发下载、跳过已完成文件、节流进度刷新等。

## 项目结构

```text
课程回放/
├── main.py                    # 主入口：默认启动 GUI，也支持 CLI 模式
├── gui.py                     # PyQt5 图形界面和批量任务调度
├── crawler.py                 # 课程平台接口封装
├── downloader.py              # HLS/m3u8 下载、音频抽取、音视频合并
├── transcriber.py             # faster-whisper 转写逻辑
├── summarizer.py              # OpenAI 兼容接口总结逻辑
├── config.py                  # 默认配置与 settings.json 读写
├── performance_utils.py       # GUI/下载性能辅助工具
├── requirements.txt           # 主程序依赖
├── standalone-login/
│   ├── login.py               # 独立 CAS 登录脚本
│   ├── omis.onnx              # 验证码 OCR 模型
│   └── requirements.txt       # 登录脚本依赖
└── tests/                     # 单元测试
```

运行过程中会生成以下本地目录或文件：

```text
downloads/       # 下载的视频/音频
audio/           # 音频文件
transcripts/     # 转写结果
subtitles/       # 字幕文件
summaries/       # 总结文件
cookies.txt      # 平台 Cookie，本地敏感文件
settings.json    # 本地配置，本地敏感文件
```

这些目录和敏感配置已在 `.gitignore` 中排除。

## 环境要求

### Python

建议使用 Python 3.10 或更新版本。

### ffmpeg

下载和音频抽取依赖 `ffmpeg` 和 `ffprobe`，需要提前安装并加入系统 `PATH`。

检查命令：

```powershell
ffmpeg -version
ffprobe -version
```

### 可选 GPU

转写使用 `faster-whisper`。如果机器有 CUDA 环境，可在设置中选择 `cuda`；否则使用 `cpu`。

## 安装依赖

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

如果需要使用独立登录脚本，还需要安装登录模块依赖：

```powershell
python -m pip install -r standalone-login/requirements.txt
```

## 配置说明

默认配置在 [config.py](/E:/脚本工具/课程回放/config.py) 中，首次运行后会读取或生成本地 `settings.json`。

常用配置项：

| 配置项 | 作用 |
| --- | --- |
| `base_url` | 课程平台地址 |
| `cookie_file` | Cookie 文件路径 |
| `download_dir` | 下载目录 |
| `audio_dir` | 音频目录 |
| `transcript_dir` | 转写输出目录 |
| `summary_dir` | 总结输出目录 |
| `session_id` | 平台接口请求头使用的 sessionId |
| `api_key` | OpenAI 兼容接口 Key |
| `api_base_url` | OpenAI 兼容接口地址 |
| `api_model` | 总结使用的模型 |
| `whisper_model` | Whisper 模型名称 |
| `whisper_device` | `auto`、`cuda` 或 `cpu` |
| `whisper_language` | `zh`、`en` 或 `auto` |
| `fast_download_progress` | 是否跳过下载前的远程时长探测，加快开始下载 |

GUI 的“设置”页可以修改大部分常用配置。

## 获取 Cookie

课程接口依赖有效 Cookie。可以使用 `standalone-login/login.py` 自动登录并写入 Cookie。

### 准备账号文件

在 `standalone-login/` 目录下创建 `account.txt`：

```text
用户名,密码
```

注意：`account.txt` 已被 `.gitignore` 排除，请不要提交账号密码。

### 执行登录

```powershell
cd standalone-login
python login.py
```

登录成功后会写入：

- `standalone-login/cookie.txt`
- 项目根目录 `cookies.txt`

### 强制重新登录

登录脚本默认会先检查已有 Cookie 是否仍可用；如果可用，会跳过完整 CAS 登录以节省时间。

如需强制重新登录：

```powershell
python login.py --force-login
```

## 启动 GUI

在项目根目录执行：

```powershell
python main.py
```

GUI 基本流程：

1. 启动后自动加载学期。
2. 选择学期，加载课程列表。
3. 选择课程，加载回放列表。
4. 勾选一个或多个回放。
5. 选择视频画面。
6. 选择下载视频或仅下载音频。
7. 等待下载完成。
8. 如需转写，切换到“转写”页选择音频文件。
9. 如需总结，切换到“总结”页选择转写文件并填写 API 配置。

## 命令行模式

也可以使用交互式 CLI：

```powershell
python main.py cli
```

CLI 会依次提示：

1. 选择学期。
2. 选择课程。
3. 选择回放。
4. 选择视频画面。
5. 选择是否仅下载音频。
6. 选择是否转写。
7. 选择是否总结。

## 下载逻辑

下载器位于 [downloader.py](/E:/脚本工具/课程回放/downloader.py)。

视频下载：

- 使用 `ffmpeg` 直接读取 m3u8。
- 默认复制视频/音频流，不做重新编码。
- 输出为 `mp4`。

仅音频下载：

- 优先并发下载 HLS 分片到临时目录。
- 再通过本地 playlist 抽取音频流。
- 遇到加密或异常情况时回退到 `ffmpeg` 顺序下载。

下载性能优化：

- 批量任务会提前并发获取流信息。
- 批量下载使用有限并发，避免过度占用网络和磁盘。
- 已存在且大小合理的媒体文件会直接跳过。
- 默认跳过远程 m3u8 时长探测，加快下载启动。
- GUI 进度更新做了节流，降低界面刷新压力。
- 下载完成后仅增量加入本次下载的音频文件，不再默认递归扫描完整目录。

## 转写逻辑

转写器位于 [transcriber.py](/E:/脚本工具/课程回放/transcriber.py)。

输出文件：

- `*_transcript.json`：结构化结果，包含语言、时长、分段和全文。
- `.txt`：纯文本，每段一行。
- `.srt`：字幕文件。

常用模型：

```text
tiny
base
small
medium
large-v3
large-v3-turbo
```

如果显存或内存不足，建议使用较小模型。

## 总结逻辑

总结器位于 [summarizer.py](/E:/脚本工具/课程回放/summarizer.py)。

它使用 OpenAI 兼容 Chat Completions API。你可以在 GUI 中配置：

- API Key
- API 地址
- 模型名称

如果转写文本较长，程序会分段总结后再合并。

## 测试

运行全部单元测试：

```powershell
python -m unittest discover -s tests
```

当前测试覆盖：

- Cookie 复用探测。
- GUI/下载性能工具。
- 下载进度快速模式。
- 已完成文件判断。
- 音频文件识别。
- 已下载回放时间索引。
- 有限并发任务调度。

## 常见问题

### 启动后课程加载失败

优先检查：

1. `cookies.txt` 是否存在。
2. Cookie 是否过期。
3. `settings.json` 中 `base_url` 和 `cookie_file` 是否正确。
4. 网络是否能访问课程平台。

可以尝试重新登录：

```powershell
cd standalone-login
python login.py --force-login
```

### 下载失败或输出文件为 0 字节

优先检查：

1. 是否安装了 `ffmpeg` 和 `ffprobe`。
2. 当前回放画面是否真的有视频流。
3. Cookie 是否过期。
4. 下载目录是否有写入权限。

### GUI 显示乱码

源码和终端环境可能存在编码不一致。建议：

1. 使用支持 UTF-8 的编辑器打开项目。
2. PowerShell 中设置 UTF-8 输出：

```powershell
chcp 65001
```

3. 确认文件以 UTF-8 保存。

### 转写很慢

这是正常现象，取决于：

- 音频长度。
- Whisper 模型大小。
- 是否使用 GPU。
- CPU/GPU 性能。

想更快可以选择较小模型，例如 `small` 或 `medium`。

### 总结失败

优先检查：

1. API Key 是否填写。
2. API Base URL 是否兼容 OpenAI Chat Completions。
3. 模型名称是否正确。
4. 网络是否可访问 API 服务。

## 开发注意事项

- 不要提交 `cookies.txt`、`settings.json`、`account.txt` 等敏感文件。
- 不要提交 `downloads/`、`audio/`、`transcripts/` 等大文件目录。
- 修改爬虫接口前，尽量保持 `CourseCrawler` 的公开方法签名稳定。
- 下载相关优化优先放在 GUI 调度层或 `performance_utils.py`，避免破坏平台接口逻辑。
- 提交前建议运行：

```powershell
python -m unittest discover -s tests
```

## 最近的性能优化提交

```text
perf(login): reuse valid cookies before CAS login
perf(gui): cache course navigation data
perf(download): prefetch stream metadata
perf(download): limit concurrent batch downloads
perf(download): skip completed media files
perf(download): skip remote duration probes
perf(gui): throttle download progress updates
perf(gui): append downloaded audio incrementally
perf(gui): index downloaded replay markers
```

