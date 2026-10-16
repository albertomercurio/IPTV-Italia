import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_playlists import main, validate_playlist_text


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

    def test_warns_when_signed_token_expires_within_30_days(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        expiry = int((now + timedelta(days=10)).timestamp())
        content = (
            "#EXTM3U\n#EXTINF:-1,Channel One\n"
            f"https://example.org/live.m3u8?hdnea=st=1~exp={expiry}~hmac=abc\n"
        )
        errors, warnings = validate_playlist_text("sample.m3u", content, now=now)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("expires at", warnings[0][1])

    def test_cli_can_fail_on_expiry_warnings(self):
        content = (
            "#EXTM3U\n#EXTINF:-1,Channel One\n"
            "https://example.org/live.m3u8?hdnea=st=1~exp=1609459200~hmac=abc\n"
        )
        with TemporaryDirectory() as directory:
            playlist = Path(directory) / "sample.m3u"
            playlist.write_text(content, encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([str(playlist)]), 0)
            with redirect_stdout(output):
                self.assertEqual(main(["--fail-on-warning", str(playlist)]), 1)
        self.assertIn("expired", output.getvalue())

    def test_rai_relinker_urls_use_https_and_current_user_agent(self):
        repo_root = Path(__file__).resolve().parents[1]
        for filename in ("iptvita.m3u", "iptvitaplus.m3u"):
            with self.subTest(playlist=filename):
                content = (repo_root / filename).read_text(encoding="utf-8")
                urls = [
                    line.strip()
                    for line in content.splitlines()
                    if "mediapolis.rai.it/relinker/relinkerServlet.htm?" in line
                ]
                self.assertEqual(len(urls), 14)
                self.assertTrue(all(url.startswith("https://") for url in urls))
                self.assertTrue(
                    all("forceUserAgent=rainet/4.0.5" in url for url in urls)
                )


if __name__ == "__main__":
    unittest.main()
