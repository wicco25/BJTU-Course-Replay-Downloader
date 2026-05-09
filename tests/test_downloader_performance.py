import unittest
from unittest.mock import patch

from downloader import VideoDownloader


class FakeCrawler:
    session_id = "sid"

    class Session:
        cookies = {}

    session = Session()


class DownloadDurationTests(unittest.TestCase):
    def test_fast_progress_skips_remote_duration_probe(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["fast_download_progress"] = True

        with patch.object(downloader, "_get_hls_duration") as probe:
            duration = downloader._get_remote_download_duration("http://example/lesson.m3u8")

        self.assertIsNone(duration)
        probe.assert_not_called()

    def test_precise_progress_keeps_duration_probe_available(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["fast_download_progress"] = False

        with patch.object(downloader, "_get_hls_duration", return_value=12.5) as probe:
            duration = downloader._get_remote_download_duration("http://example/lesson.m3u8")

        self.assertEqual(duration, 12.5)
        probe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
