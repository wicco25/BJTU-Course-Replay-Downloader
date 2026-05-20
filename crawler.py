"""课程平台爬虫模块 - 负责与课程平台的所有HTTP交互"""

import requests
import re
import os
import subprocess
import sys
import time
from bs4 import BeautifulSoup
from config import BASE_DIR, load_config, get_download_path


AUTH_EXPIRED_MARKERS = (
    "cas.bjtu.edu.cn",
    "/auth/login",
    "/auth/sso",
    "login",
    "session",
    "expired",
    "unauthorized",
    "nullpointerexception",
    "系统发生了未处理",
    "登录",
    "未登录",
    "认证",
    "过期",
)


class CourseCrawler:
    """课程平台爬虫，封装所有API调用"""

    def __init__(self):
        cfg = load_config()
        self.base_url = cfg["base_url"]
        self.session_id = cfg["session_id"]
        self.cookie_file = cfg["cookie_file"]
        self.auto_relogin = cfg.get("auto_relogin", True)
        self._relogin_attempted = False
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
        })
        self._load_cookies()

    def _load_cookies(self):
        self.session.cookies.clear()
        if os.path.exists(self.cookie_file):
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        self.session.cookies.set(key.strip(), value.strip())
            print(f"[Crawler] 已加载Cookie: {len(self.session.cookies)} 条")
        else:
            print(f"[Crawler] 警告: Cookie文件不存在: {self.cookie_file}")

    def _api_get(self, path, params=None, extra_headers=None):
        """GET请求（JSON API）"""
        return self._request_json("GET", path, params=params,
                                  extra_headers=extra_headers)

    def _api_post(self, path, data=None, extra_headers=None):
        """POST请求（JSON API）"""
        return self._request_json("POST", path, data=data or {},
                                  extra_headers=extra_headers)

    def _request_json(self, method, path, params=None, data=None,
                      extra_headers=None, allow_relogin=True):
        url = f"{self.base_url}{path}"
        headers = {"sessionId": self.session_id}
        if extra_headers:
            headers.update(extra_headers)
        try:
            if method == "POST":
                resp = self.session.post(
                    url, data=data or {}, headers=headers,
                    timeout=30, allow_redirects=False,
                )
            else:
                resp = self.session.get(
                    url, params=params, headers=headers,
                    timeout=30, allow_redirects=False,
                )
            resp.encoding = "utf-8"
            try:
                payload = resp.json() if resp.text else {}
            except ValueError:
                payload = None

            if self._looks_auth_expired(resp, payload):
                if allow_relogin and self._refresh_login():
                    return self._request_json(
                        method, path, params=params, data=data,
                        extra_headers=extra_headers, allow_relogin=False,
                    )
                return {}
            return payload or {}
        except Exception as e:
            print(f"[Crawler] {method} {url} 失败: {e}")
            return {}

    def _looks_auth_expired(self, resp, payload):
        location = resp.headers.get("Location", "")
        if resp.is_redirect or resp.is_permanent_redirect:
            return True
        if resp.status_code in (401, 403):
            return True
        if payload is not None:
            text = " ".join(
                str(payload.get(key, ""))
                for key in ("MSG", "msg", "message", "error")
            ).lower()
            return any(marker.lower() in text for marker in AUTH_EXPIRED_MARKERS)
        text = f"{location}\n{resp.text[:1000]}".lower()
        return any(marker.lower() in text for marker in AUTH_EXPIRED_MARKERS)

    def _refresh_login(self):
        if not self.auto_relogin or self._relogin_attempted:
            return False
        self._relogin_attempted = True
        script = os.path.join(BASE_DIR, "standalone-login", "login.py")
        if not os.path.exists(script):
            print(f"[Crawler] 自动登录脚本不存在: {script}")
            return False

        cmd = [
            sys.executable,
            script,
            "--cookie",
            self.cookie_file,
            "--base-url",
            self.base_url,
            "--session-id",
            self.session_id,
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=os.path.dirname(script),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as e:
            print(f"[Crawler] 自动重新登录失败: {e}")
            return False
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            print(f"[Crawler] 自动重新登录失败: {detail}")
            return False
        print("[Crawler] 自动重新登录成功，已重新加载 Cookie")
        self._load_cookies()
        return True

    def _get_page(self, path, params=None):
        """获取HTML页面"""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.encoding = "gbk"
            return resp.text
        except Exception as e:
            print(f"[Crawler] 获取页面 {url} 失败: {e}")
            return ""

    # ==================== 学期 ====================

    def get_semesters(self):
        """获取学期列表"""
        data = self._api_get(
            "/back/rp/common/teachCalendar.shtml",
            params={"method": "queryCurrentXq"}
        )
        if data.get("STATUS") == "0":
            return data.get("result", [])
        return []

    # ==================== 课程列表 ====================

    def get_courses(self, xq_code, page=1, page_size=100):
        """获取指定学期的课程列表"""
        data = self._api_get(
            "/back/coursePlatform/course.shtml",
            params={
                "method": "getCourseList",
                "pagesize": page_size,
                "page": page,
                "xqCode": xq_code,
            }
        )
        if data.get("STATUS") == "0":
            return {
                "courses": data.get("courseList", []),
                "total": data.get("total", 0),
                "page": data.get("page", page),
                "total_page": data.get("totalPage", 0),
            }
        return {"courses": [], "total": 0, "page": page, "total_page": 0}

    def get_all_courses(self, xq_code):
        """获取指定学期的所有课程（自动翻页）"""
        first = self.get_courses(xq_code, page=1, page_size=100)
        all_courses = first["courses"]
        total_page = first["total_page"]
        for p in range(2, total_page + 1):
            result = self.get_courses(xq_code, page=p, page_size=100)
            all_courses.extend(result["courses"])
        return all_courses

    # ==================== 课程模块菜单 ====================

    def get_course_modules(self):
        """获取课程左侧菜单模块（含视频回放入口）"""
        data = self._api_get(
            "/back/coursePlatform/coursePlatform.shtml",
            params={"method": "getUserModulePermission"}
        )
        if data.get("STATUS") == "0":
            return data.get("result", [])
        return []

    # ==================== 教学日历（回放列表） ====================

    def get_teaching_calendar(self, c_id):
        """获取课程的教学日历（即回放课次列表），c_id为课程数据库ID"""
        data = self._api_get(
            "/back/rp/common/teachCalendar.shtml",
            params={
                "method": "toDisplyTeachCourses",
                "courseId": c_id,
            }
        )
        if data.get("STATUS") == "0":
            result = data.get("courseSchedList", [])
            for item in result:
                if isinstance(item.get("params"), str):
                    item["params"] = self.parse_params(item["params"])
            return result
        return []

    # ==================== 视频流URL ====================

    def get_stream_info(self, sched_id, user_level=1, user_id=""):
        """获取课次的视频流信息（m3u8地址）"""
        data = self._api_get(
            "/back/rp/common/teachCalendar.shtml",
            params={
                "method": "toDisplyCourseSchedDetail",
                "courseSchedId": sched_id,
                "userLevel": user_level,
                "userId": user_id,
            }
        )
        if data.get("STATUS") == "0":
            res = data.get("res", {})
            stream_map = res.get("streamMap", {})
            if stream_map.get("haveStream") == "1":
                return {
                    "teacher_url": stream_map.get("teaStreamHlsUrl", ""),
                    "student_url": stream_map.get("stuStreamHlsUrl", ""),
                    "course_url": stream_map.get("vgaStreamHlsUrl", ""),
                    "teacher_closeup_url": stream_map.get("teaCloseUpStreamHlsUrl", ""),
                    "student_closeup_url": stream_map.get("stuCloseUpStreamHlsUrl", ""),
                    "movie_url": stream_map.get("movieStreamHlsUrl", ""),
                    "rp_size": stream_map.get("rpSize", 0),
                    "rp_id": stream_map.get("rpId", ""),
                    "public_type": stream_map.get("publicRpType", ""),
                    "point_status": res.get("pointStatus", ""),
                    "course_sched": res.get("courseSched", {}),
                }
        return {}

    # ==================== 资源列表 ====================

    def get_resource_list(self, course_id, xkh_id, xq_code, c_ids,
                          teacher_id="", calendar_id="", page=1, page_size=10):
        """获取课程资源列表"""
        data = self._api_post(
            "/back/course/courseInfo.shtml?method=queryMyUploadResourceForCourseList",
            data={
                "currentPage": page,
                "pageSize": page_size,
                "courseId": course_id,
                "xkhId": xkh_id,
                "xqCode": xq_code,
                "cIds": c_ids,
                "teacherId": teacher_id,
                "calendarId": calendar_id,
            }
        )
        if data.get("STATUS") in ("0", "2"):
            return data.get("result", [])
        return []

    # ==================== 字幕获取 ====================

    def get_subtitle(self, rp_id):
        """获取视频字幕(VTT格式)"""
        url = f"{self.base_url}/webservices/qxkt.shtml"
        params = {
            "method": "getSubtitleFile",
            "rpId": rp_id,
            "type": "vtt",
        }
        try:
            resp = self.session.get(url, params=params,
                                    headers={"sessionId": self.session_id},
                                    timeout=30)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            print(f"[Crawler] 获取字幕失败: {e}")
            return ""

    # ==================== 视频下载 ====================

    def get_m3u8_content(self, url):
        """获取m3u8文件内容"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            print(f"[Crawler] 获取m3u8失败: {e}")
            return ""

    def get_ts_segment(self, url):
        """下载单个ts分片"""
        try:
            resp = self.session.get(url, timeout=60)
            return resp.content if resp.status_code == 200 else None
        except Exception as e:
            print(f"[Crawler] 下载分片失败 {url}: {e}")
            return None

    # ==================== 辅助方法 ====================

    @staticmethod
    def parse_params(params):
        """解析Java风格的params字符串 {key=value, key=value}"""
        if isinstance(params, dict):
            return params
        if isinstance(params, str):
            result = {}
            for match in re.finditer(r'(\w+)=([^,}]+)', params):
                result[match.group(1)] = match.group(2).strip()
            return result
        return {}

    def parse_course_info(self, course):
        """从课程数据中提取关键信息"""
        return {
            "id": course.get("id"),
            "name": course.get("name", ""),
            "course_num": course.get("course_num", ""),
            "teacher_name": course.get("teacher_name", ""),
            "teacher_id": course.get("teacher_id"),
            "fz_id": course.get("fz_id", ""),
            "xq_code": course.get("xq_code", ""),
            "pic": course.get("pic", ""),
        }

    def build_stream_urls(self, stream_info):
        """从stream_info提取可下载的视频URL列表"""
        urls = []
        mapping = {
            "course_url": "课件画面",
            "teacher_url": "教师画面",
            "student_url": "学生画面",
        }
        for key, label in mapping.items():
            url = stream_info.get(key, "")
            if url and url != "noVideo":
                urls.append({"url": url, "label": label, "key": key})
        return urls
