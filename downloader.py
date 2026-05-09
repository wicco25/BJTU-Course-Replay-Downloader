"""下载器模块 - 负责从m3u8/HLS流下载视频或提取音频"""

import os
import re
import subprocess
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

from config import load_config


def _without_proxy_env():
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    ):
        env.pop(key, None)
    return env


class VideoDownloader:
    """HLS视频/音频下载器"""

    def __init__(self, crawler):
        self.crawler = crawler
        self.cfg = load_config()
        self._segment_local = threading.local()

    def download_m3u8(self, m3u8_url, output_path, progress_callback=None):
        """
        下载m3u8视频为mp4文件。
        优先使用ffmpeg直接下载，失败时回退到手动下载ts分片合并。
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        if self.cfg.get("use_ytdlp", True):
            result = self._download_with_ytdlp(
                m3u8_url, output_path, progress_callback
            )
            if result:
                return result
            print("[Downloader] yt-dlp video download failed, fallback to parallel HLS")
        if self.cfg.get("parallel_hls_download", True):
            result = self._download_hls_parallel(
                m3u8_url, output_path, media_kind="video",
                progress_callback=progress_callback,
            )
            if result:
                return result
            print("[Downloader] parallel video download failed, fallback to ffmpeg")
        return self._download_with_ffmpeg(m3u8_url, output_path, progress_callback)

    def _download_with_ffmpeg(self, m3u8_url, output_path, progress_callback=None):
        """使用ffmpeg下载HLS流"""
        duration = self._get_remote_download_duration(m3u8_url)
        if progress_callback:
            progress_callback(0)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-headers", f"sessionId: {self.crawler.session_id}",
            "-i", m3u8_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-f", "mp4",
            "-progress", "pipe:1",
            "-nostats",
            output_path
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    progress_callback(1.0)
                return output_path
            else:
                print("[Downloader] ffmpeg失败")
                return None
        except FileNotFoundError:
            print("[Downloader] ffmpeg未找到，请安装ffmpeg")
            return None

    def extract_audio(self, video_path, audio_path, progress_callback=None):
        """从视频提取音频(mp3)"""
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        duration = self._get_media_duration(video_path)
        if progress_callback:
            progress_callback(0)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "128k",
            "-progress", "pipe:1",
            "-nostats",
            audio_path
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(audio_path):
                if progress_callback:
                    progress_callback(1.0)
                return audio_path
            print("[Downloader] ffmpeg失败")
            return None
        except FileNotFoundError:
            print("[Downloader] ffmpeg未找到")
            return None

    def download_audio_only(self, m3u8_url, audio_path, progress_callback=None):
        """直接从m3u8拷贝音频流（跳过视频下载步骤）"""
        if self.cfg.get("use_ytdlp", True):
            result = self._download_audio_with_ytdlp(
                m3u8_url, audio_path, progress_callback
            )
            if result:
                return result
            print("[Downloader] yt-dlp audio download failed, fallback to parallel HLS")
        result = self._download_hls_parallel(
            m3u8_url, audio_path, media_kind="audio",
            progress_callback=progress_callback,
        )
        if result:
            return result
        print("[Downloader] 并发音频下载失败，回退到ffmpeg顺序下载")
        return self._download_audio_with_ffmpeg(m3u8_url, audio_path, progress_callback)

    def _download_audio_with_ffmpeg(self, m3u8_url, audio_path, progress_callback=None):
        """使用ffmpeg顺序读取HLS并拷贝音频流。"""
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        duration = self._get_remote_download_duration(m3u8_url)
        if progress_callback:
            progress_callback(0)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-headers", f"sessionId: {self.crawler.session_id}",
            "-i", m3u8_url,
            "-map", "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            audio_path
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(audio_path):
                if progress_callback:
                    progress_callback(1.0)
                return audio_path
            print("[Downloader] ffmpeg失败")
            return None
        except FileNotFoundError:
            print("[Downloader] ffmpeg未找到")
            return None

    def _download_audio_parallel(self, m3u8_url, audio_path, progress_callback=None):
        """并发下载HLS分片到本地，再用ffmpeg抽取音频流。"""
        return self._download_hls_parallel(
            m3u8_url, audio_path, media_kind="audio",
            progress_callback=progress_callback,
        )

    def _download_with_ytdlp(self, m3u8_url, output_path, progress_callback=None):
        if progress_callback:
            progress_callback(0)
        cmd = self._build_ytdlp_cmd(m3u8_url, output_path)
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=_without_proxy_env(),
            )
            for line in process.stdout:
                self._emit_ytdlp_progress(line, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(output_path):
                if progress_callback:
                    progress_callback(1.0)
                return output_path
            return None
        except FileNotFoundError:
            return None

    def _download_audio_with_ytdlp(self, m3u8_url, audio_path,
                                   progress_callback=None):
        os.makedirs(os.path.dirname(audio_path), exist_ok=True)
        temp_video = audio_path + ".source.mp4"
        try:
            result = self._download_with_ytdlp(
                m3u8_url,
                temp_video,
                lambda pct: progress_callback(pct * 0.9)
                if progress_callback else None,
            )
            if not result:
                return None
            audio = self._extract_audio_from_media(
                temp_video,
                audio_path,
                lambda pct: progress_callback(0.9 + pct * 0.1)
                if progress_callback else None,
            )
            if audio and progress_callback:
                progress_callback(1.0)
            return audio
        finally:
            try:
                if os.path.exists(temp_video):
                    os.remove(temp_video)
            except OSError:
                pass

    def _build_ytdlp_cmd(self, m3u8_url, output_path):
        workers = self._bounded_segment_workers(999999)
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--newline",
            "--no-playlist",
            "--force-overwrites",
            "--no-part",
            "-N",
            str(workers),
            "--add-header",
            f"sessionId:{self.crawler.session_id}",
        ]
        cookie_header = self._cookie_header()
        if cookie_header:
            cmd.extend(["--add-header", f"Cookie:{cookie_header}"])
        cmd.extend(["-o", output_path, m3u8_url])
        return cmd

    def _cookie_header(self):
        cookies = getattr(self.crawler.session, "cookies", {})
        if hasattr(cookies, "get_dict"):
            cookies = cookies.get_dict()
        return "; ".join(
            f"{key}={value}" for key, value in dict(cookies).items()
        )

    def _extract_audio_from_media(self, media_path, audio_path,
                                  progress_callback=None):
        duration = self._get_media_duration(media_path)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-i", media_path,
            "-map", "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            audio_path,
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(audio_path):
                return audio_path
            return None
        except FileNotFoundError:
            return None

    def _download_hls_parallel(self, m3u8_url, output_path, media_kind,
                               progress_callback=None):
        """Download simple HLS segments concurrently, then remux locally."""
        content = self.crawler.get_m3u8_content(m3u8_url)
        if not content:
            return None

        lines = content.splitlines()
        segment_lines = [
            line.strip() for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not segment_lines:
            return None
        if any("#EXT-X-KEY" in line for line in lines):
            return None
        if any(line.lstrip().startswith("#EXT-X-MAP") for line in lines):
            return None

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_dir = output_path + ".parts"
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)

        try:
            segment_names = [
                f"seg_{idx:05d}.ts" for idx in range(1, len(segment_lines) + 1)
            ]
            segment_urls = [urljoin(m3u8_url, segment) for segment in segment_lines]
            total = len(segment_urls)
            done = 0
            workers = self._bounded_segment_workers(total)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        self._download_segment,
                        segment_url,
                        os.path.join(temp_dir, segment_names[idx]),
                    )
                    for idx, segment_url in enumerate(segment_urls)
                ]
                for future in as_completed(futures):
                    future.result()
                    done += 1
                    if progress_callback:
                        progress_callback(min(done / total * 0.9, 0.9))

            playlist_path = os.path.join(temp_dir, "playlist.m3u8")
            self._write_local_playlist(playlist_path, lines, segment_names)

            if media_kind == "audio":
                result = self._extract_audio_from_local_playlist(
                    playlist_path, output_path,
                    lambda pct: progress_callback(0.9 + pct * 0.1)
                    if progress_callback else None,
                )
            else:
                result = self._remux_video_from_local_playlist(
                    playlist_path, output_path,
                    lambda pct: progress_callback(0.9 + pct * 0.1)
                    if progress_callback else None,
                )

            if result:
                if progress_callback:
                    progress_callback(1.0)
                return result
            return None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _write_local_playlist(self, playlist_path, lines, segment_names):
        seg_idx = 0
        with open(playlist_path, "w", encoding="utf-8", newline="\n") as f:
            for raw_line in lines:
                stripped = raw_line.strip()
                if stripped and not stripped.startswith("#"):
                    f.write(segment_names[seg_idx] + "\n")
                    seg_idx += 1
                else:
                    f.write(raw_line + "\n")

    def _bounded_segment_workers(self, total):
        try:
            workers = int(self.cfg.get("segment_workers", 16))
        except (TypeError, ValueError):
            workers = 16
        workers = min(32, max(4, workers))
        return min(workers, max(total, 1))

    def _segment_retries(self):
        try:
            retries = int(self.cfg.get("segment_retries", 3))
        except (TypeError, ValueError):
            retries = 3
        return min(8, max(0, retries))

    def _download_segment(self, url, output_path):
        session = self._get_segment_session()
        retries = self._segment_retries()
        tmp_path = output_path + ".tmp"
        last_error = None

        for attempt in range(retries + 1):
            try:
                with session.get(url, stream=True, timeout=(10, 60)) as resp:
                    resp.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1024 * 256):
                            if chunk:
                                f.write(chunk)
                os.replace(tmp_path, output_path)
                return
            except Exception as exc:
                last_error = exc
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
                if attempt < retries:
                    time.sleep(0.4 * (attempt + 1))
        raise last_error

    def _get_segment_session(self):
        session = getattr(self._segment_local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "sessionId": self.crawler.session_id,
            })
            session.cookies.update(self.crawler.session.cookies)
            self._segment_local.session = session
        return session

    def _extract_audio_from_local_playlist(self, playlist_path, audio_path,
                                           progress_callback=None):
        duration = self._get_hls_duration(playlist_path)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-allowed_extensions", "ALL",
            "-protocol_whitelist", "file,crypto,data,pipe",
            "-i", playlist_path,
            "-map", "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-nostats",
            audio_path,
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(audio_path):
                return audio_path
            print("[Downloader] 本地分片抽取音频失败")
            return None
        except FileNotFoundError:
            print("[Downloader] ffmpeg未找到")
            return None

    def _remux_video_from_local_playlist(self, playlist_path, output_path,
                                         progress_callback=None):
        duration = self._get_hls_duration(playlist_path)
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-allowed_extensions", "ALL",
            "-protocol_whitelist", "file,crypto,data,pipe",
            "-i", playlist_path,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            "-f", "mp4",
            "-progress", "pipe:1",
            "-nostats",
            output_path,
        ]
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, env=_without_proxy_env()
            )
            for line in process.stdout:
                self._emit_progress(line, duration, progress_callback)

            process.wait()
            if process.returncode == 0 and os.path.exists(output_path):
                return output_path
            print("[Downloader] local segment video remux failed")
            return None
        except FileNotFoundError:
            print("[Downloader] ffmpeg not found")
            return None

    def merge_audio_video(self, video_path, audio_path, output_path):
        """合并视频和音频轨道"""
        cmd = [
            "ffmpeg", "-y", "-nostdin", "-loglevel", "error",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        try:
            subprocess.run(
                cmd, capture_output=True, check=True, timeout=600,
                env=_without_proxy_env()
            )
            return output_path if os.path.exists(output_path) else None
        except Exception as e:
            print(f"[Downloader] 合并失败: {e}")
            return None

    def _get_hls_duration(self, m3u8_url):
        """尽量从m3u8获取总时长，供下载进度换算为0-1。"""
        if os.path.exists(m3u8_url):
            with open(m3u8_url, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = self.crawler.get_m3u8_content(m3u8_url)
        duration = 0.0
        if content:
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    value = line.split(":", 1)[1].split(",", 1)[0]
                    try:
                        duration += float(value)
                    except ValueError:
                        pass
        if duration > 0:
            return duration
        return self._get_media_duration(m3u8_url, headers=f"sessionId: {self.crawler.session_id}")

    def _get_remote_download_duration(self, m3u8_url):
        """Skip the extra remote playlist probe when fast progress is enabled."""
        if self.cfg.get("fast_download_progress", True):
            return None
        return self._get_hls_duration(m3u8_url)

    def _get_media_duration(self, source, headers=None):
        """用ffprobe获取媒体时长；失败时返回None，进度仍会在完成时置满。"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
        ]
        if headers:
            cmd.extend(["-headers", headers])
        cmd.append(source)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=False,
                env=_without_proxy_env() if headers else None
            )
            value = result.stdout.strip().splitlines()[0]
            duration = float(value)
            return duration if duration > 0 else None
        except Exception:
            return None

    @staticmethod
    def _emit_progress(line, duration, progress_callback):
        if not progress_callback or "out_time_ms=" not in line:
            return
        if not duration:
            return
        try:
            us_val = int(line.split("=", 1)[1].strip())
            seconds = us_val / 1_000_000
            progress_callback(min(max(seconds / duration, 0), 0.999))
        except ValueError:
            pass

    @staticmethod
    def _emit_ytdlp_progress(line, progress_callback):
        if not progress_callback:
            return
        match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
        if not match:
            return
        try:
            progress_callback(min(float(match.group(1)) / 100.0, 0.999))
        except ValueError:
            pass
