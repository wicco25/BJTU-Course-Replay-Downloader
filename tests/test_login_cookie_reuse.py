import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


LOGIN_PATH = Path(__file__).resolve().parents[1] / "standalone-login" / "login.py"
SPEC = importlib.util.spec_from_file_location("standalone_login", LOGIN_PATH)
login_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(login_mod)


class FakeResponse:
    def __init__(self, status_code=200, location="", payload=None, text=""):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.is_redirect = bool(location)
        self.is_permanent_redirect = False
        self.payload = payload
        self.text = text

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    def __init__(self, response):
        if isinstance(response, (list, tuple)):
            self.responses = list(response)
        else:
            self.responses = [response]
        self.headers = {}
        self.cookies = {}
        self.trust_env = True
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class CookieReuseTests(unittest.TestCase):
    def test_probe_reuses_valid_cookie_without_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=200, payload={"STATUS": "0", "courseList": []}),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                cookies = login_mod._probe_cookie_valid(str(cookie_path), "http://example/ve")

        self.assertEqual(cookies, {"JSESSIONID": "abc"})
        self.assertFalse(fake_session.trust_env)
        self.assertEqual(fake_session.calls[0][1]["timeout"], login_mod.REQUEST_TIMEOUT)
        self.assertEqual(
            fake_session.calls[0][1]["params"],
            {"method": "queryCurrentXq"},
        )
        self.assertEqual(
            fake_session.calls[0][1]["headers"]["sessionId"],
            login_mod.DEFAULT_SESSION_ID,
        )

    def test_probe_rejects_auth_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=302, location="https://cas.bjtu.edu.cn/auth/login/"),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                cookies = login_mod._probe_cookie_valid(str(cookie_path), "http://example/ve")

        self.assertEqual(cookies, {})

    def test_probe_rejects_html_login_page_with_200(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=200, text="<html>login</html>"),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                cookies = login_mod._probe_cookie_valid(str(cookie_path), "http://example/ve")

        self.assertEqual(cookies, {})

    def test_probe_rejects_api_status_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=200, payload={"STATUS": "1", "MSG": "expired"}),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                cookies = login_mod._probe_cookie_valid(str(cookie_path), "http://example/ve")

        self.assertEqual(cookies, {})

    def test_probe_rejects_course_endpoint_server_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=500, text="java.lang.NullPointerException"),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                cookies = login_mod._probe_cookie_valid(str(cookie_path), "http://example/ve")

        self.assertEqual(cookies, {})

    def test_probe_uses_supplied_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_path = Path(tmp) / "cookie.txt"
            login_mod._write_cookie_file(str(cookie_path), {"JSESSIONID": "abc"})
            fake_session = FakeSession([
                FakeResponse(
                    status_code=200,
                    payload={
                        "STATUS": "0",
                        "result": [{"xqCode": "2025202602", "currentFlag": 2}],
                    },
                ),
                FakeResponse(status_code=200, payload={"STATUS": "0", "courseList": []}),
            ])

            with patch.object(login_mod.requests, "Session", return_value=fake_session):
                login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="custom"
                )

        self.assertEqual(fake_session.calls[0][1]["headers"]["sessionId"], "custom")


if __name__ == "__main__":
    unittest.main()
