import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

SPEC = importlib.util.spec_from_file_location("v2_generate", Path(__file__).resolve().parents[1] / "generate.py")
generate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate)
SETTINGS = {"LATITUDE": "31.2304", "LONGITUDE": "121.4737", "CITY_NAME": "SHANGHAI"}
WEATHER = {
    "temp": 18, "humidity": 55, "condition": "Partly Cloudy", "high": 22, "low": 12,
    "timezone": "Asia/Shanghai", "weather_time": "2026-11-13T00:00",
    "forecast": [{"date": date(2026, 11, 13 + index), "condition": "Thunderstorm with Heavy Hail",
                  "high": 22, "low": 12} for index in range(7)],
}


class GenerateTests(unittest.TestCase):
    def test_settings_do_not_require_v1_env_or_ssh(self):
        settings = generate.load_settings(SETTINGS)
        self.assertEqual(settings["CONTACT_INFO"], "")
        self.assertEqual(settings["LATITUDE"], 31.2304)
        for value in ("nan", "inf", "91", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generate.load_settings({**SETTINGS, "LATITUDE": value})

    def test_weather_preserves_api_timezone_and_forecast(self):
        data = {
            "timezone": "Asia/Shanghai",
            "current": {"temperature_2m": 18.4, "relative_humidity_2m": 55,
                        "weather_code": 2, "time": "2026-11-13T00:00"},
            "daily": {"time": [date(2026, 11, 12 + index).isoformat() for index in range(8)],
                      "weather_code": [2] * 8, "temperature_2m_max": [22.1] * 8,
                      "temperature_2m_min": [12.3] * 8},
        }
        with patch.object(generate.requests, "get") as get:
            get.return_value.json.return_value = data
            result = generate.get_weather(generate.load_settings(SETTINGS))
            get.return_value.raise_for_status.assert_called_once()
            self.assertEqual(result["timezone"], "Asia/Shanghai")
            self.assertEqual(len(result["forecast"]), 7)
            self.assertEqual(result["forecast"][0]["date"], date(2026, 11, 13))
            data["daily"]["time"].pop()
            with self.assertRaisesRegex(ValueError, "eight forecast days"):
                generate.get_weather(generate.load_settings(SETTINGS))

    def test_both_orientations_publish_verified_rgb_with_matching_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / "photos"
            photos.mkdir()
            Image.new("RGB", (120, 200), "green").save(photos / "test.jpg")
            for orientation in ("portrait", "landscape"):
                with self.subTest(orientation=orientation):
                    image = generate.build_image(
                        WEATHER, generate.load_settings(SETTINGS), photos, orientation,
                        now=datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc),
                    )
                    metadata = generate.publish(image, root / orientation, WEATHER, orientation)
                    content = (root / orientation / metadata["image"]).read_bytes()
                    self.assertEqual(hashlib.sha256(content).hexdigest(), metadata["sha256"])
                    self.assertEqual(image.size, (1620, 2160))
                    self.assertEqual(image.mode, "RGB")
                    manifest = (root / orientation / "latest.sha256").read_text()
                    self.assertEqual(manifest, f"{metadata['sha256']}  {metadata['image']}\n")
                    self.assertEqual(json.loads((root / orientation / "latest.json").read_text()), metadata)

    def test_date_heading_uses_weather_timezone_not_runner_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            Image.new("RGB", (10, 10)).save(Path(directory) / "photo.png")
            with patch.object(generate.ImageDraw.ImageDraw, "text", autospec=True) as text:
                generate.build_image(WEATHER, generate.load_settings(SETTINGS), directory,
                                     now=datetime(2026, 11, 12, 16, 30, tzinfo=timezone.utc))
            rendered = [call.args[2] for call in text.call_args_list]
            self.assertIn("SHANGHAI  \u2022  FRIDAY, NOV 13", rendered)
            self.assertIn("Updated 00:30 CST", rendered)

    def test_empty_photos_and_bad_output_fail_without_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "No photos"):
                generate.build_image(WEATHER, generate.load_settings(SETTINGS), directory)
            with self.assertRaisesRegex(ValueError, "opaque"):
                generate.publish(Image.new("RGBA", (1620, 2160)), directory, WEATHER, "portrait")
            self.assertFalse((Path(directory) / "latest.sha256").exists())

    def test_network_failure_preserves_existing_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "latest.sha256"
            manifest.write_text("previous publication\n")
            with (
                patch.dict(generate.os.environ, SETTINGS),
                patch.object(generate.requests, "get", side_effect=generate.requests.ReadTimeout),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(generate.main(["--output-dir", directory]), 1)
            self.assertEqual(manifest.read_text(), "previous publication\n")
            self.assertIn("ReadTimeout", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()