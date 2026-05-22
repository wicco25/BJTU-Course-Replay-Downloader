"""课程回放下载工具 - 主入口

用法:
    python main.py            # 启动GUI
    python main.py cli        # 命令行模式（交互式）
"""

import sys
import os


def _clear_dead_proxy_env():
    dead_proxy_values = {"http://127.0.0.1:9", "https://127.0.0.1:9"}
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        if os.environ.get(key, "").lower() in dead_proxy_values:
            os.environ.pop(key, None)


_clear_dead_proxy_env()


def run_gui():
    from gui import main as gui_main
    gui_main()


def run_cli():
    """命令行交互模式"""
    from crawler import CourseCrawler
    from downloader import VideoDownloader
    from config import load_config

    cfg = load_config()
    c = CourseCrawler()
    dl = VideoDownloader(c)

    # 1. 选择学期
    semesters = c.get_semesters()
    if not semesters:
        print("没有可用的学期")
        return

    print("\n可用学期:")
    for i, s in enumerate(semesters):
        flag = " [当前]" if s.get("currentFlag") == 2 else ""
        print(f"  [{i}] {s.get('CNAME', s.get('xqCode'))}{flag}")

    idx = int(input("\n选择学期序号: ").strip())
    xq_code = semesters[idx]["xqCode"]

    # 2. 选择课程
    courses = c.get_all_courses(xq_code)
    if not courses:
        print("该学期没有课程")
        return

    print(f"\n课程列表 ({len(courses)} 门):")
    for i, co in enumerate(courses):
        print(f"  [{i}] {co['name']} | {co['course_num']} | {co.get('teacher_name','')}")

    idx = int(input("\n选择课程序号: ").strip())
    course = courses[idx]
    print(f"已选择: {course['name']}")

    # 3. 选择回放
    calendar = c.get_teaching_calendar(course["id"])
    if not calendar:
        print("该课程没有回放")
        return

    print(f"\n回放列表 ({len(calendar)} 次):")
    for i, cal in enumerate(calendar):
        print(f"  [{i}] {cal.get('courseBetween','')} | "
              f"videoId={cal.get('params',{}).get('videoId','N/A')}")

    idx = int(input("\n选择回放序号: ").strip())
    sched = calendar[idx]
    sched_id = sched["id"]

    # 4. 获取视频流
    print("\n获取视频流...")
    stream = c.get_stream_info(sched_id, user_level=1, user_id="170179")
    if not stream:
        print("无法获取视频流")
        return

    urls = c.build_stream_urls(stream)
    print(f"可用画面 ({len(urls)} 个):")
    for i, u in enumerate(urls):
        print(f"  [{i}] {u['label']}")

    idx = int(input("\n选择画面序号 (默认0): ").strip() or "0")
    stream_url = urls[idx]
    stream_key = stream_url["key"]

    # 5. 下载
    audio_only = input("仅下载音频? (y/N): ").strip().lower() == "y"
    ext = "m4a" if audio_only else "mp4"
    safe_name = "".join(
        c if c.isalnum() or c in "._- " else "_" for c in course["name"]
    )
    time_str = sched.get("courseBetween", "").replace(":", "").replace(" ", "_")
    filename = f"{safe_name}_{time_str}_{stream_url['label']}.{ext}"
    output_path = os.path.join(cfg["download_dir"], filename)
    os.makedirs(cfg["download_dir"], exist_ok=True)

    print(f"\n开始下载: {filename}")
    m3u8_url = stream[stream_key]

    def progress_cb(pct):
        print(f"\r下载进度: {int(pct*100)}%", end="", flush=True)

    if audio_only:
        result = dl.download_audio_only(m3u8_url, output_path, progress_cb)
    else:
        result = dl.download_m3u8(m3u8_url, output_path, progress_cb)

    if not result:
        print("\n下载失败")
        return

    print(f"\n下载完成: {result}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        run_cli()
    else:
        run_gui()
