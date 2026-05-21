import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crawler import CourseCrawler


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None, location=""):
        self.status_code = status_code
        self.payload = payload
        self.text = text if payload is None else text or "{}"
        self.headers = {"Location": location} if location else {}
        self.is_redirect = bool(location)
        self.is_permanent_redirect = False
        self.encoding = None

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)


class CrawlerReloginTests(unittest.TestCase):
    def make_crawler(self, responses, session_id="sid"):
        crawler = CourseCrawler.__new__(CourseCrawler)
        crawler.base_url = "http://example/ve"
        crawler.session_id = session_id
        crawler.cookie_file = "cookies.txt"
        crawler.auto_relogin = True
        crawler._relogin_attempted = False
        crawler.session = FakeSession(responses)
        return crawler

    def test_api_get_relogs_and_retries_login_page(self):
        crawler = self.make_crawler([
            FakeResponse(status_code=200, text="<html>login</html>"),
            FakeResponse(status_code=200, payload={"STATUS": "0", "result": [1]}),
        ])

        with patch.object(crawler, "_refresh_login", return_value=True) as refresh:
            result = crawler._api_get("/back/rp/common/teachCalendar.shtml")

        self.assertEqual(result, {"STATUS": "0", "result": [1]})
        refresh.assert_called_once()
        self.assertEqual(len(crawler.session.calls), 2)
        self.assertFalse(crawler.session.calls[0][2]["allow_redirects"])

    def test_api_get_does_not_retry_business_json(self):
        crawler = self.make_crawler([
            FakeResponse(status_code=200, payload={"STATUS": "1", "MSG": "no data"}),
        ])

        with patch.object(crawler, "_refresh_login") as refresh:
            result = crawler._api_get("/back/rp/common/teachCalendar.shtml")

        self.assertEqual(result, {"STATUS": "1", "MSG": "no data"})
        refresh.assert_not_called()

    def test_api_get_relogs_on_expired_json_message(self):
        crawler = self.make_crawler([
            FakeResponse(status_code=200, payload={"STATUS": "1", "MSG": "session expired"}),
            FakeResponse(status_code=200, payload={"STATUS": "0", "result": []}),
        ])

        with patch.object(crawler, "_refresh_login", return_value=True) as refresh:
            result = crawler._api_get("/back/rp/common/teachCalendar.shtml")

        self.assertEqual(result, {"STATUS": "0", "result": []})
        refresh.assert_called_once()

    def test_api_get_refreshes_before_request_when_session_id_missing(self):
        crawler = self.make_crawler([
            FakeResponse(status_code=200, payload={"STATUS": "0", "result": []}),
        ], session_id="")

        def refresh():
            crawler.session_id = "fresh"
            return True

        with patch.object(crawler, "_refresh_login", side_effect=refresh) as refresh_mock:
            result = crawler._api_get("/back/rp/common/teachCalendar.shtml")

        self.assertEqual(result, {"STATUS": "0", "result": []})
        refresh_mock.assert_called_once()
        self.assertEqual(crawler.session.calls[0][2]["headers"]["sessionId"], "fresh")

    def test_refresh_login_reloads_session_id_from_settings(self):
        crawler = self.make_crawler([], session_id="")

        with patch("crawler.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            with patch("crawler.load_config", return_value={"session_id": "fresh"}):
                with patch.object(crawler, "_load_cookies") as load_cookies:
                    self.assertTrue(crawler._refresh_login())

        load_cookies.assert_called_once()
        self.assertEqual(crawler.session_id, "fresh")


if __name__ == "__main__":
    unittest.main()
