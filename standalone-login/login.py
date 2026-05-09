# coding=utf-8
"""BJTU CAS 登录模块 — 独立可复用

用法：
    python login.py [--account account.txt] [--cookie cookie.txt] [--model omis.onnx] [--base-url URL]

    account.txt 格式：第一行为 用户名,密码
    cookie.txt 输出：key=value 逐行格式，供爬虫直接读取
"""

import argparse
import io
import json
import os
import sys
from typing import Dict
from urllib import parse

import onnxruntime
import requests
from bs4 import BeautifulSoup
from numpy import array, expand_dims, float32
from PIL import Image

# ============================================================
# 验证码 OCR（本地 ONNX 模型）
# ============================================================

CHARSET = [" ", "9", "5", "-", "7", "0", "2", "6", "1", "3", "x", "8", "=", "4", "+"]


class CaptchaOCR:
    """BJTU CAS 数学验证码识别器"""

    def __init__(self, model_path: str):
        self._ort_session = onnxruntime.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )

    def solve(self, img_bytes: bytes) -> int:
        """识别验证码图片并计算数学表达式结果"""
        image = Image.open(io.BytesIO(img_bytes))
        image = image.resize(
            (int(image.size[0] * (64 / image.size[1])), 64), Image.LANCZOS
        ).convert("L")

        image = array(image).astype(float32)
        image = expand_dims(image, axis=0) / 255.0
        image = (image - 0.456) / 0.224

        ort_inputs = {"input1": array([image]).astype(float32)}
        ort_outs = self._ort_session.run(None, ort_inputs)

        result = []
        last_item = 0
        for item in ort_outs[0][0]:
            if item == last_item:
                continue
            last_item = item
            if item != 0:
                result.append(CHARSET[item])

        expression = "".join(result)
        expression = (
            expression.replace("x", "*")
            .replace("×", "*")
            .replace("=", "")
            .strip()
        )
        return eval(expression, {"__builtins__": {}}, {})


# ============================================================
# CAS SSO 认证核心
# ============================================================

BASE_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = (5, 15)
DEFAULT_SESSION_ID = "9BEC92261A9FBC5ECF299C45D4C0468A"


def _new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(BASE_HEADERS)
    return session


def _load_cookie_file(cookie_path: str) -> Dict[str, str]:
    cookies = {}
    if not os.path.exists(cookie_path):
        return cookies
    with open(cookie_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def _write_cookie_file(cookie_path: str, cookies: Dict[str, str]):
    os.makedirs(os.path.dirname(os.path.abspath(cookie_path)), exist_ok=True)
    tmp_path = cookie_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for key, value in cookies.items():
            f.write(f"{key}={value}\n")
    try:
        os.replace(tmp_path, cookie_path)
    except PermissionError:
        with open(cookie_path, "w", encoding="utf-8") as f:
            for key, value in cookies.items():
                f.write(f"{key}={value}\n")
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _request_probe_json(session: requests.Session, url: str,
                        params: Dict[str, object],
                        session_id: str) -> Dict[str, object]:
    response = session.get(
        url,
        params=params,
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "sessionId": session_id,
        },
        allow_redirects=False,
        timeout=REQUEST_TIMEOUT,
    )
    if response.is_redirect or response.is_permanent_redirect:
        return {}
    if response.status_code >= 400:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _probe_cookie_valid(cookie_path: str, base_url: str,
                        session_id: str = DEFAULT_SESSION_ID) -> Dict[str, str]:
    cookies = _load_cookie_file(cookie_path)
    if not cookies:
        return {}

    session = _new_session()
    session.cookies.update(cookies)
    try:
        semester_url = (
            f"{base_url.rstrip('/')}/back/rp/common/teachCalendar.shtml"
        )
        semester_data = _request_probe_json(
            session, semester_url, {"method": "queryCurrentXq"}, session_id
        )
    except requests.RequestException:
        return {}

    if semester_data.get("STATUS") != "0":
        return {}
    semesters = semester_data.get("result") or []
    xq_code = ""
    for semester in semesters:
        if semester.get("currentFlag") == 2:
            xq_code = semester.get("xqCode", "")
            break
    if not xq_code and semesters:
        xq_code = semesters[0].get("xqCode", "")
    if not xq_code:
        return {}

    try:
        courses_url = f"{base_url.rstrip('/')}/back/coursePlatform/course.shtml"
        course_data = _request_probe_json(
            session,
            courses_url,
            {
                "method": "getCourseList",
                "pagesize": 1,
                "page": 1,
                "xqCode": xq_code,
            },
            session_id,
        )
    except requests.RequestException:
        return {}
    if course_data.get("STATUS") != "0":
        return {}

    refreshed = dict(cookies)
    if hasattr(session.cookies, "get_dict"):
        refreshed.update(session.cookies.get_dict())
    else:
        refreshed.update(dict(session.cookies))
    return refreshed


def _load_project_session_id(script_dir: str) -> str:
    settings_path = os.path.normpath(os.path.join(script_dir, "..", "settings.json"))
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return DEFAULT_SESSION_ID
    return settings.get("session_id") or DEFAULT_SESSION_ID


def _get_initial_page(session: requests.Session) -> requests.Response:
    """获取 CAS 登录页面"""
    response = session.get(
        "https://mis.bjtu.edu.cn/auth/sso/?next=/",
        allow_redirects=False,
        timeout=REQUEST_TIMEOUT,
    )
    url = response.headers.get("Location")
    response = session.get(url, allow_redirects=False, timeout=REQUEST_TIMEOUT)
    url = "https://cas.bjtu.edu.cn" + response.headers.get("Location")
    return session.get(url, allow_redirects=False, timeout=REQUEST_TIMEOUT)


def _get_platform_cookie(session: requests.Session, base_url: str):
    """SSO 登录后访问课程平台，获取平台自己的 session cookie"""
    session.get(base_url, allow_redirects=True, timeout=REQUEST_TIMEOUT)


def _extract_login_info(html: str) -> Dict[str, str]:
    """从 CAS 登录页提取 csrf token、验证码 ID、next URL"""
    soup = BeautifulSoup(html, "html.parser")
    captcha_img = soup.find("img", class_="captcha")
    captcha_id = captcha_img["src"].split("/")[-2]
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    csrfmiddlewaretoken = csrf_input["value"]
    next_input = soup.find("input", {"name": "next"})
    next_url = next_input["value"].replace("&amp;", "&")
    return {
        "captcha_id": captcha_id,
        "csrfmiddlewaretoken": csrfmiddlewaretoken,
        "next_url": next_url,
    }


def _solve_captcha(session: requests.Session, captcha_id: str, ocr: CaptchaOCR) -> int:
    """下载验证码图片并求解"""
    captcha_img = session.get(
        f"https://cas.bjtu.edu.cn/image/{captcha_id}",
        timeout=REQUEST_TIMEOUT,
    ).content
    return ocr.solve(captcha_img)


def _do_login(
    session: requests.Session,
    login_info: Dict[str, str],
    captcha_result: int,
    username: str,
    password: str,
) -> requests.Response:
    """向 CAS 提交登录表单"""
    url = f"https://cas.bjtu.edu.cn/auth/login/?next={login_info['next_url']}"
    payload = {
        "next": login_info["next_url"],
        "csrfmiddlewaretoken": login_info["csrfmiddlewaretoken"],
        "loginname": username,
        "password": password,
        "captcha_0": login_info["captcha_id"],
        "captcha_1": captcha_result,
    }
    session.headers.update({
        "authority": "cas.bjtu.edu.cn",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://cas.bjtu.edu.cn",
        "referer": (
            f"https://cas.bjtu.edu.cn/auth/login/"
            f"?next={parse.quote(login_info['next_url'])}"
        ),
    })
    return session.post(
        url, data=payload, allow_redirects=False, timeout=REQUEST_TIMEOUT
    )


def _follow_redirects(session: requests.Session, response: requests.Response):
    """登录后跟随 CAS → MIS 重定向链，完成 MIS 登录"""
    url = "https://cas.bjtu.edu.cn" + response.headers.get("Location")
    response = session.get(url, allow_redirects=False, timeout=REQUEST_TIMEOUT)

    session.headers.update({"authority": "mis.bjtu.edu.cn"})
    url = response.headers.get("Location")
    # allow_redirects=True 确保完成 MIS 登录（跟随 MIS 的最终重定向）
    session.get(url, allow_redirects=True)


def _platform_oauth_login(session: requests.Session):
    """通过 MIS 模块入口触发课程平台 OAuth 认证，获取已认证的 JSESSIONID

    认证链路:
        MIS /module/module/28/
        → 平台 /oauth/api/user/thirdLogin
        → CAS /o/authorize
        → 平台 /oauth/token/callBack?code=xxx
        → 平台 /ve/s.shtml (已认证)
    """
    # 清理登录过程残留的请求头，避免干扰后续请求
    for key in ("content-type", "origin", "referer", "authority"):
        session.headers.pop(key, None)

    # 1. 通过 MIS 模块入口访问课程平台
    resp = session.get(
        "https://mis.bjtu.edu.cn/module/module/28/",
        allow_redirects=False, timeout=REQUEST_TIMEOUT,
    )
    loc = resp.headers.get("Location", "")

    # 2. 跟随 OAuth 重定向链直到完成
    for _ in range(10):
        if not loc:
            break
        if loc.startswith("/"):
            if loc.startswith("/o/"):
                loc = "https://cas.bjtu.edu.cn" + loc
            else:
                loc = "http://123.121.147.7:88" + loc
        resp = session.get(loc, allow_redirects=False, timeout=REQUEST_TIMEOUT)
        loc = resp.headers.get("Location", "")




# ============================================================
# 公开 API
# ============================================================


def login(username: str, password: str, model_path: str,
          base_url: str = "http://123.121.147.7:88/ve") -> Dict[str, str]:
    """BJTU CAS 登录，返回 cookies_dict

    参数:
        username:   MIS 系统学号
        password:   MIS 系统密码
        model_path: ONNX 验证码模型路径（omis.onnx）
        base_url:   课程平台地址

    返回:
        cookies_dict: requests.Session cookies 字典
    """
    ocr = CaptchaOCR(model_path)
    session = _new_session()

    # 1. 获取 CAS 登录页面
    response = _get_initial_page(session)

    # 2. 提取登录表单信息
    login_info = _extract_login_info(response.text)

    # 3. 验证码识别
    captcha_result = _solve_captcha(session, login_info["captcha_id"], ocr)

    # 4. 提交登录
    response = _do_login(session, login_info, captcha_result, username, password)

    # 5. 跟随重定向链，完成 MIS 登录
    _follow_redirects(session, response)

    # 6. 通过 MIS 模块入口触发课程平台 OAuth 认证，获取已认证的 JSESSIONID
    _platform_oauth_login(session)

    return session.cookies.get_dict()


# ============================================================
# 命令行入口
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description="BJTU CAS 登录 — 获取认证 Cookie"
    )
    parser.add_argument(
        "--account",
        default="account.txt",
        help="账号文件路径，第一行为 用户名,密码（默认 account.txt）",
    )
    parser.add_argument(
        "--cookie",
        default="cookie.txt",
        help="Cookie 输出文件路径（默认 cookie.txt）",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="ONNX 模型路径（默认 ./omis.onnx 或 ../src/omis.onnx）",
    )
    parser.add_argument(
        "--base-url",
        default="http://123.121.147.7:88/ve",
        help="课程平台地址（默认 http://123.121.147.7:88/ve）",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="课程平台 API 使用的 sessionId；默认读取项目 settings.json。",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="Force a fresh CAS login instead of reusing an existing cookie.",
    )
    args = parser.parse_args()

    # 解析账号文件
    if not os.path.exists(args.account):
        print(f"[错误] 账号文件不存在: {args.account}")
        print("请创建 account.txt，第一行格式: 用户名,密码")
        sys.exit(1)

    with open(args.account, "r", encoding="utf-8") as f:
        line = f.readline().strip()
    if "," not in line:
        print(f"[错误] account.txt 格式不正确，应为: 用户名,密码")
        sys.exit(1)
    username, password = line.split(",", 1)

    # 定位模型文件
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = args.model
    if model_path is None:
        candidates = [
            os.path.join(script_dir, "omis.onnx"),
            os.path.join(script_dir, "..", "src", "omis.onnx"),
        ]
        for candidate in candidates:
            if os.path.exists(os.path.normpath(candidate)):
                model_path = os.path.normpath(candidate)
                break
    if model_path is None or not os.path.exists(model_path):
        print(f"[错误] 找不到 ONNX 模型文件，请用 --model 指定路径")
        sys.exit(1)

    print(f"[信息] 账号: {username}")
    print(f"[信息] 模型: {model_path}")
    print(f"[信息] 目标: {args.base_url}")

    # 执行登录
    root_cookie = os.path.join(script_dir, "..", "cookies.txt")
    session_id = args.session_id or _load_project_session_id(script_dir)
    if not args.force_login:
        cookies = _probe_cookie_valid(args.cookie, args.base_url, session_id)
        if cookies:
            _write_cookie_file(root_cookie, cookies)
            print(f"[Info] Existing cookie is valid, skipped CAS login: {args.cookie}")
            print(f"[Info] Cookie synced to project root: {root_cookie}")
            return

    try:
        cookies = login(username, password, model_path, args.base_url)
    except Exception as e:
        print(f"[错误] 登录失败: {e}")
        sys.exit(1)

    print(f"[成功] Cookie 数量: {len(cookies)}")

    # 写入本地 cookie 文件
    _write_cookie_file(args.cookie, cookies)
    print(f"[信息] Cookie 已写入: {args.cookie}")

    # 同时替换根目录 cookies.txt
    if os.path.abspath(args.cookie) != os.path.abspath(root_cookie):
        _write_cookie_file(root_cookie, cookies)
        print(f"[信息] 已同步到根目录: {root_cookie}")


if __name__ == "__main__":
    main()
