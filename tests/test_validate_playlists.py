import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_playlists import validate_playlist_text


class PlaylistValidationTests(unittest.TestCase):
    def test_accepts_player_directive_between_metadata_and_url(self):
        content = (
            "#EXTM3U\n"
            '#EXTINF:-1 group-title="News",Channel One\n'
            "#EXTVLCOPT:http-user-agent=ExamplePlayer\n"
            "https://example.org/live/index.m3u8\n"
        )
        errors, warnings = validate_playlist_text("sample.m3u", content)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_reports_missing_stream_url(self):
        content = "#EXTM3U\n#EXTINF:-1,Channel One\n"
        errors, _ = validate_playlist_text("sample.m3u", content)
        self.assertTrue(any("no stream URL" in message for _, message in errors))

    def test_rejects_relative_stream_url(self):
        content = "#EXTM3U\n#EXTINF:-1,Channel One\n/live/index.m3u8\n"
        errors, _ = validate_playlist_text("sample.m3u", content)
        self.assertTrue(any("absolute HTTP(S)" in message for _, message in errors))

    def test_warns_on_expired_signed_token_without_failing_structure(self):
        content = (
            "#EXTM3U\n#EXTINF:-1,Channel One\n"
            "https://example.org/live.m3u8?hdnea=st=1~exp=1609459200~hmac=abc\n"
        )
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        errors, warnings = validate_playlist_text("sample.m3u", content, now=now)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("expired", warnings[0][1])


if __name__ == "__main__":
    unittest.main()
