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


class AudioPlaylistUrlTests(unittest.TestCase):
    def test_audio_playlist_url_replaces_playlist_name(self):
        downloader = VideoDownloader(FakeCrawler())

        url = downloader._audio_playlist_url("http://example/vod/lesson.mp4/playlist.m3u8")

        self.assertEqual(url, "http://example/vod/lesson.mp4/playlist-a1.m3u8")

    def test_audio_playlist_url_preserves_query_and_fragment(self):
        downloader = VideoDownloader(FakeCrawler())

        url = downloader._audio_playlist_url(
            "http://example/vod/lesson.mp4/playlist.m3u8?token=abc#frag"
        )

        self.assertEqual(
            url,
            "http://example/vod/lesson.mp4/playlist-a1.m3u8?token=abc#frag",
        )

    def test_audio_playlist_url_does_not_rewrite_existing_audio_playlist(self):
        downloader = VideoDownloader(FakeCrawler())

        url = downloader._audio_playlist_url(
            "http://example/vod/lesson.mp4/playlist-a1.m3u8?token=abc"
        )

        self.assertEqual(
            url,
            "http://example/vod/lesson.mp4/playlist-a1.m3u8?token=abc",
        )


class ParallelDownloadTests(unittest.TestCase):
    def test_video_download_prefers_parallel_hls(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = False
        downloader.cfg["parallel_hls_download"] = True

        with patch.object(
            downloader, "_download_hls_parallel", return_value="out.mp4"
        ) as parallel, patch.object(downloader, "_download_with_ffmpeg") as ffmpeg:
            result = downloader.download_m3u8("http://example/lesson.m3u8", "downloads/out.mp4")

        self.assertEqual(result, "out.mp4")
        parallel.assert_called_once()
        self.assertEqual(parallel.call_args.kwargs["media_kind"], "video")
        ffmpeg.assert_not_called()

    def test_video_download_falls_back_to_ffmpeg(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = False
        downloader.cfg["parallel_hls_download"] = True

        with patch.object(
            downloader, "_download_hls_parallel", return_value=None
        ) as parallel, patch.object(
            downloader, "_download_with_ffmpeg", return_value="fallback.mp4"
        ) as ffmpeg:
            result = downloader.download_m3u8("http://example/lesson.m3u8", "downloads/out.mp4")

        self.assertEqual(result, "fallback.mp4")
        parallel.assert_called_once()
        ffmpeg.assert_called_once()

    def test_audio_download_uses_parallel_hls_audio_mode(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = False

        with patch.object(
            downloader, "_download_hls_parallel", return_value="out.m4a"
        ) as parallel, patch.object(downloader, "_download_audio_with_ffmpeg") as ffmpeg:
            result = downloader.download_audio_only(
                "http://example/lesson.mp4/playlist.m3u8",
                "audio/out.m4a",
            )

        self.assertEqual(result, "out.m4a")
        self.assertEqual(
            parallel.call_args.args[0],
            "http://example/lesson.mp4/playlist-a1.m3u8",
        )
        self.assertEqual(parallel.call_args.kwargs["media_kind"], "audio")
        ffmpeg.assert_not_called()

    def test_audio_download_falls_back_to_original_video_playlist(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = False

        with patch.object(
            downloader, "_download_hls_parallel", side_effect=[None, "out.m4a"]
        ) as parallel, patch.object(
            downloader, "_download_audio_with_ffmpeg", return_value=None
        ):
            result = downloader.download_audio_only(
                "http://example/lesson.mp4/playlist.m3u8",
                "audio/out.m4a",
            )

        self.assertEqual(result, "out.m4a")
        self.assertEqual(
            [call.args[0] for call in parallel.call_args_list],
            [
                "http://example/lesson.mp4/playlist-a1.m3u8",
                "http://example/lesson.mp4/playlist.m3u8",
            ],
        )

    def test_segment_workers_are_bounded(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["segment_workers"] = 99

        self.assertEqual(downloader._bounded_segment_workers(100), 32)
        self.assertEqual(downloader._bounded_segment_workers(2), 2)

    def test_video_download_prefers_ytdlp(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = True

        with patch.object(
            downloader, "_download_with_ytdlp", return_value="out.mp4"
        ) as ytdlp, patch.object(downloader, "_download_hls_parallel") as parallel:
            result = downloader.download_m3u8("http://example/lesson.m3u8", "downloads/out.mp4")

        self.assertEqual(result, "out.mp4")
        ytdlp.assert_called_once()
        parallel.assert_not_called()

    def test_video_download_falls_back_from_ytdlp_to_parallel_hls(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = True

        with patch.object(
            downloader, "_download_with_ytdlp", return_value=None
        ) as ytdlp, patch.object(
            downloader, "_download_hls_parallel", return_value="parallel.mp4"
        ) as parallel:
            result = downloader.download_m3u8("http://example/lesson.m3u8", "downloads/out.mp4")

        self.assertEqual(result, "parallel.mp4")
        ytdlp.assert_called_once()
        parallel.assert_called_once()

    def test_audio_download_prefers_ytdlp_audio_playlist(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["use_ytdlp"] = True

        with patch.object(
            downloader, "_download_audio_with_ytdlp", return_value="out.m4a"
        ) as ytdlp, patch.object(downloader, "_download_hls_parallel") as parallel:
            result = downloader.download_audio_only(
                "http://example/lesson.mp4/playlist.m3u8",
                "audio/out.m4a",
            )

        self.assertEqual(result, "out.m4a")
        ytdlp.assert_called_once_with(
            "http://example/lesson.mp4/playlist-a1.m3u8",
            "audio/out.m4a",
            None,
        )
        parallel.assert_not_called()

    def test_ytdlp_audio_download_does_not_extract_from_temp_video(self):
        downloader = VideoDownloader(FakeCrawler())

        with patch.object(
            downloader, "_download_with_ytdlp", return_value="audio/out.m4a"
        ) as ytdlp, patch.object(downloader, "_extract_audio_from_media") as extract:
            result = downloader._download_audio_with_ytdlp(
                "http://example/lesson.mp4/playlist-a1.m3u8",
                "audio/out.m4a",
            )

        self.assertEqual(result, "audio/out.m4a")
        ytdlp.assert_called_once_with(
            "http://example/lesson.mp4/playlist-a1.m3u8",
            "audio/out.m4a",
            None,
        )
        extract.assert_not_called()

    def test_ytdlp_command_passes_headers_and_fragment_workers(self):
        downloader = VideoDownloader(FakeCrawler())
        downloader.cfg["segment_workers"] = 12

        cmd = downloader._build_ytdlp_cmd("http://example/lesson.m3u8", "downloads/out.mp4")

        self.assertIn("yt_dlp", cmd)
        self.assertIn("-N", cmd)
        self.assertEqual(cmd[cmd.index("-N") + 1], "12")
        self.assertIn("sessionId:sid", cmd)
        self.assertEqual(cmd[-2:], ["downloads/out.mp4", "http://example/lesson.m3u8"])


if __name__ == "__main__":
    unittest.main()
