# 课程回放下载工具

> 北京交通大学课程回放平台的本地下载工具。登录一次，批量下载，告别卡顿播放。

## 为什么做这个项目

课程平台在线播放经常卡顿，且每次观看都需要重新登录。下载到本地后，不仅播放流畅，还能方便地做 AI 转录、摘要等后处理。

## 这个工具能做什么

- **自动登录** BJTU CAS/MIS，无需手动操作
- **浏览课程** 按学期查看所有课程及其回放列表
- **下载视频或音频**，保存到本地随时观看
- **图形界面**批量勾选下载，也支持命令行
- 自动跳过已下载文件，断线后自动重新登录

下载到本地后，你可以用 AI 工具做转文字、生成摘要等二次处理。

---

## 使用前准备

在开始之前，你需要安装两个东西：**Python** 和 **ffmpeg**。

### 第一步：安装 Python（已安装可跳过）

建议安装 **Python 3.10 或更新版本**。

👉 前往 [python.org](https://www.python.org/downloads/) 下载安装包。

> ⚠️ Windows 用户安装时，请勾选底部的 **"Add Python to PATH"** 选项，否则后续命令会报错。

### 第二步：安装 ffmpeg（如不需要转音频功能则可不装）

ffmpeg 是处理视频和音频的核心工具，**必须安装**。

**Windows：**

```powershell
winget install ffmpeg
```

或前往 [ffmpeg.org](https://ffmpeg.org/download.html) 手动下载，并将 `bin` 目录添加到系统 PATH。

**macOS：**

```bash
brew install ffmpeg
```

**验证安装是否成功：**

```powershell
ffmpeg -version
ffprobe -version
```

两条命令都输出版本号，说明安装成功。

---

## 快速上手

### 第一步：下载项目

点击页面右上角的 **Code → Download ZIP**，解压到任意目录。

或者用 git：

```bash
git clone https://github.com/wicco25/BJTU-Course-Replay-Downloader.git
cd BJTU-Course-Replay-Downloader
```

### 第二步：安装 Python 依赖

在项目根目录打开终端（命令提示符 / PowerShell），运行：

```powershell
python -m pip install -r requirements.txt
```

> 💡 如果提示 `pip` 找不到，可以试试 `python3 -m pip install -r requirements.txt`

### 第三步：填写账号信息

在 `standalone-login/` 目录下，新建一个名为 `account.txt` 的文件，内容如下：

```
你的学号,你的密码
```

例如：

```
21xxxxxx,mypassword123
```

> ⚠️ 注意：用英文逗号分隔，不要有多余空格，不要加引号。

### 第四步：启动程序

在项目根目录运行：

```powershell
python main.py
```

程序会自动打开图形界面，登录后即可选择学期、课程和回放进行下载。

---


## 项目结构

```text
.
├── main.py                    # 主入口，默认启动 GUI，也支持 CLI
├── gui.py                     # PyQt5 图形界面
├── crawler.py                 # 课程平台接口封装
├── downloader.py              # HLS/m3u8 下载、音频抽取、媒体处理
├── config.py                  # 默认配置与 settings.json 读写
├── performance_utils.py       # 下载和任务调度辅助工具
├── requirements.txt           # 项目依赖
├── standalone-login/
│   ├── login.py               # 独立 CAS/MIS 登录脚本
│   └── omis.onnx              # 验证码 OCR 模型
└── tests/                     # 单元测试
```

---

## 常见问题

**Q：登录失败怎么办？**
A：检查 `account.txt` 中的账号密码是否正确，格式为 `学号,密码`（英文逗号）。


---

