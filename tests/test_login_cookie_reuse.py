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
    def test_extract_session_id_from_absolute_url(self):
        url = "http://example/ve/back/coursePlatform/coursePlatform.shtml?method=x&sessionId=6264B6"

        self.assertEqual(login_mod._extract_session_id_from_url(url), "6264B6")

    def test_extract_session_id_from_relative_url(self):
        url = "/ve/back/coursePlatform/coursePlatform.shtml?method=x&sessionId=6264B6"

        self.assertEqual(login_mod._extract_session_id_from_url(url), "6264B6")

    def test_extract_session_id_returns_empty_for_missing_value(self):
        url = "/ve/back/coursePlatform/coursePlatform.shtml?method=x"

        self.assertEqual(login_mod._extract_session_id_from_url(url), "")

    def test_extract_session_id_from_html_text(self):
        html = '<a href="/ve/back/coursePlatform/coursePlatform.shtml?sessionId=htmlsid&method=x">x</a>'

        self.assertEqual(login_mod._extract_session_id_from_text(html), "htmlsid")
        self.assertEqual(login_mod._extract_session_ids_from_text(html), ["htmlsid"])

    def test_extract_session_id_prefers_ajax_header_from_html_text(self):
        html = """
        XMLHttpRequest.setRequestHeader("sessionId", 'apisid');
        <a href="/ve/back/coursePlatform/coursePlatform.shtml?sessionId=menusid&method=x">x</a>
        """

        self.assertEqual(
            login_mod._extract_session_ids_from_text(html),
            ["apisid", "menusid"],
        )

    def test_platform_oauth_login_returns_session_id_from_redirect(self):
        fake_session = FakeSession([
            FakeResponse(
                status_code=302,
                location="/ve/back/coursePlatform/coursePlatform.shtml?method=toCoursePlatformIndex&sessionId=dynamic",
            ),
            FakeResponse(status_code=200),
        ])

        with patch.object(
            login_mod, "_select_valid_session_id",
            side_effect=lambda _session, _base_url, candidates: candidates[0],
        ):
            session_id = login_mod._platform_oauth_login(fake_session, "http://example/ve")

        self.assertEqual(session_id, "dynamic")
        self.assertEqual(
            fake_session.calls[1][0],
            "http://example/ve/back/coursePlatform/coursePlatform.shtml?method=toCoursePlatformIndex&sessionId=dynamic",
        )

    def test_platform_oauth_login_falls_back_to_index_html(self):
        fake_session = FakeSession([
            FakeResponse(status_code=302, location="http://example/oauth/api/user/thirdLogin"),
            FakeResponse(status_code=200),
            FakeResponse(
                status_code=200,
                text='<a href="/ve/back/coursePlatform/coursePlatform.shtml?sessionId=htmlsid&method=x">x</a>',
            ),
        ])

        selections = ["", "htmlsid"]
        with patch.object(
            login_mod, "_select_valid_session_id",
            side_effect=lambda _session, _base_url, candidates: selections.pop(0),
        ):
            session_id = login_mod._platform_oauth_login(fake_session, "http://example/ve")

        self.assertEqual(session_id, "htmlsid")
        self.assertEqual(
            fake_session.calls[-1][1]["params"],
            {"method": "toCoursePlatformIndex"},
        )

    def test_write_project_session_id_merges_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            script_dir = Path(tmp) / "standalone-login"
            script_dir.mkdir()
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text('{"base_url": "http://example", "session_id": "old"}', encoding="utf-8")

            login_mod._write_project_session_id(str(script_dir), "new")

            settings = login_mod.json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertEqual(settings["base_url"], "http://example")
        self.assertEqual(settings["session_id"], "new")

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
                cookies = login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="sid"
                )

        self.assertEqual(cookies, {"JSESSIONID": "abc"})
        self.assertFalse(fake_session.trust_env)
        self.assertEqual(fake_session.calls[0][1]["timeout"], login_mod.REQUEST_TIMEOUT)
        self.assertEqual(
            fake_session.calls[0][1]["params"],
            {"method": "queryCurrentXq"},
        )
        self.assertEqual(
            fake_session.calls[0][1]["headers"]["sessionId"],
            "sid",
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
                cookies = login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="sid"
                )

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
                cookies = login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="sid"
                )

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
                cookies = login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="sid"
                )

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
                cookies = login_mod._probe_cookie_valid(
                    str(cookie_path), "http://example/ve", session_id="sid"
                )

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
