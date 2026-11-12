import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

TEST_SETTINGS = {
    "LATITUDE": "31.2304",
    "LONGITUDE": "121.4737",
    "CITY_NAME": "SHANGHAI",
    "SSH_HOST": "root@10.11.99.1",
    "CONTACT_INFO": "test@example.com | 123 456 7890",
}

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "update-dashboard.py"
SPEC = importlib.util.spec_from_file_location("update_dashboard", SCRIPT_PATH)
dashboard = importlib.util.module_from_spec(SPEC)
with (
    patch("dotenv.dotenv_values", return_value=TEST_SETTINGS),
    patch("os.path.isfile", return_value=True),
):
    SPEC.loader.exec_module(dashboard)

FORECAST = [
    {
        "date": date(2026, 11, 13) + timedelta(days=i),
        "condition": "Partly Cloudy",
        "high": 22,
        "low": 12,
    }
    for i in range(7)
]


class ConfigurationTests(unittest.TestCase):
    def test_loads_quoted_settings_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.txt"
            config_path.write_text(
                "\n".join(f'{key}="{value}"' for key, value in TEST_SETTINGS.items()),
                encoding="utf-8",
            )
            self.assertEqual(
                dashboard.load_configuration(str(config_path)),
                (31.2304, 121.4737, "SHANGHAI", "root@10.11.99.1",
                 "test@example.com | 123 456 7890"),
            )

    def test_missing_file_reports_setup_instruction(self):
        with patch.object(dashboard.os.path, "isfile", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "Copy .env.example"):
                dashboard.load_configuration("missing-settings.txt")

    def test_missing_keys_and_invalid_coordinates_are_rejected(self):
        invalid = [{k: v for k, v in TEST_SETTINGS.items() if k != key}
                   for key in TEST_SETTINGS]
        invalid += [
            {**TEST_SETTINGS, "LATITUDE": value}
            for value in ("", "invalid", "nan", "inf", "91")
        ]
        invalid.append({**TEST_SETTINGS, "LONGITUDE": "-181"})
        for settings in invalid:
            with self.subTest(settings=settings):
                with (
                    patch.object(dashboard.os.path, "isfile", return_value=True),
                    patch.object(dashboard, "dotenv_values", return_value=settings),
                ):
                    with self.assertRaises(ValueError):
                        dashboard.load_configuration("settings.txt")

    def test_empty_contact_and_literal_dollar_sign_are_supported(self):
        with (
            patch.object(dashboard.os.path, "isfile", return_value=True),
            patch.object(dashboard, "dotenv_values",
                         return_value={**TEST_SETTINGS, "CONTACT_INFO": "",
                                       "CITY_NAME": "${CITY}"}) as read_values,
        ):
            result = dashboard.load_configuration("settings.txt")
        self.assertEqual(result[2], "${CITY}")
        self.assertEqual(result[4], "")
        read_values.assert_called_once_with("settings.txt", interpolate=False)


class GetWeatherTests(unittest.TestCase):
    def test_connection_timeout_is_not_replaced_with_fake_weather(self):
        with patch.object(
            dashboard.requests, "get", side_effect=dashboard.requests.ConnectTimeout
        ):
            with self.assertRaises(dashboard.requests.ConnectTimeout):
                dashboard.get_weather()

    def test_requests_forecast_api_and_parses_current_and_daily_weather(self):
        response_data = {
            "current": {
                "temperature_2m": 18.4,
                "relative_humidity_2m": 55,
                "weather_code": 2,
            },
            "daily": {
                "time": [(date(2026, 11, 12) + timedelta(days=i)).isoformat()
                         for i in range(8)],
                "weather_code": [2] * 8,
                "temperature_2m_max": [22.1] * 8,
                "temperature_2m_min": [12.3] * 8,
            },
        }
        with patch.object(dashboard.requests, "get") as get:
            get.return_value.json.return_value = response_data

            weather = dashboard.get_weather()

        get.assert_called_once_with(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": dashboard.LATITUDE,
                "longitude": dashboard.LONGITUDE,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "forecast_days": 8,
                "timezone": "auto",
            },
            timeout=10,
        )
        get.return_value.raise_for_status.assert_called_once_with()
        self.assertEqual(
            weather,
            {
                "temp": 18,
                "humidity": 55,
                "condition": "Partly Cloudy",
                "high": 22,
                "low": 12,
                "forecast": FORECAST,
            },
        )

    def test_incomplete_forecast_is_rejected(self):
        with patch.object(dashboard.requests, "get") as get:
            get.return_value.json.return_value = {
                "current": {"weather_code": 2},
                "daily": {"time": ["2026-11-12"] * 7},
            }
            with self.assertRaisesRegex(ValueError, "eight forecast days"):
                dashboard.get_weather()

    def test_forecast_uses_each_days_condition_and_temperatures(self):
        codes = [0, 1, 2, 3, 61, 71, 95, 99]
        with patch.object(dashboard.requests, "get") as get:
            get.return_value.json.return_value = {
                "current": {
                    "weather_code": 0, "temperature_2m": 20,
                    "relative_humidity_2m": 50,
                },
                "daily": {
                    "time": [(date(2026, 11, 12) + timedelta(days=i)).isoformat()
                             for i in range(8)],
                    "weather_code": codes,
                    "temperature_2m_max": list(range(20, 28)),
                    "temperature_2m_min": list(range(10, 18)),
                },
            }
            result = dashboard.get_weather()
        self.assertEqual(len(result["forecast"]), 7)
        for i, day in enumerate(result["forecast"], start=1):
            self.assertEqual(day["date"], date(2026, 11, 12) + timedelta(days=i))
            self.assertEqual(day["condition"], dashboard.WEATHER_CODES[codes[i]])
            self.assertEqual((day["high"], day["low"]), (20 + i, 10 + i))


class MainTests(unittest.TestCase):
    def test_invalid_weather_response_prevents_generation_and_upload(self):
        with (
            patch.object(dashboard, "get_weather", side_effect=ValueError("missing days")),
            patch.object(dashboard, "build_image") as build,
            patch.object(dashboard, "push_to_remarkable") as push,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(dashboard.main([]), 1)
        build.assert_not_called()
        push.assert_not_called()
        self.assertIn("Invalid weather response", stderr.getvalue())

    def test_script_entrypoint_accepts_help_without_network_or_upload(self):
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import runpy, sys; from unittest.mock import patch; "
                f"sys.argv = [{str(SCRIPT_PATH)!r}, '--help']; "
                f"settings = {TEST_SETTINGS!r}; "
                "p = patch('dotenv.dotenv_values', return_value=settings); p.start(); "
                "q = patch('os.path.isfile', return_value=True); q.start(); "
                f"runpy.run_path({str(SCRIPT_PATH)!r}, run_name='__main__')",
            ],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("--orientation", result.stdout)
        self.assertIn("--disable-sleep-overlay", result.stdout)

    def test_network_failure_exits_without_generating_or_uploading(self):
        for error_type in (
            dashboard.requests.ConnectTimeout,
            dashboard.requests.exceptions.ProxyError,
            dashboard.requests.HTTPError,
        ):
            with self.subTest(error=error_type.__name__):
                with (
                    patch.object(dashboard, "get_weather", side_effect=error_type),
                    patch.object(dashboard, "build_image") as build,
                    patch.object(dashboard, "push_to_remarkable") as push,
                    patch("sys.stderr", new_callable=io.StringIO) as stderr,
                ):
                    self.assertEqual(dashboard.main([]), 1)

                build.assert_not_called()
                push.assert_not_called()
                message = stderr.getvalue()
                self.assertIn(error_type.__name__, message)
                self.assertIn("HTTPS_PROXY", message)
                self.assertIn("PAC", message)
                self.assertIn("No dashboard was generated or uploaded", message)

    def test_success_generates_and_uploads_weather(self):
        with (
            patch.object(dashboard, "get_weather") as get,
            patch.object(dashboard, "build_image") as build,
            patch.object(dashboard, "push_to_remarkable") as push,
        ):
            self.assertEqual(dashboard.main([]), 0)

        build.assert_called_once_with(get.return_value, orientation="portrait")
        push.assert_called_once_with(overlay_action=None)

    def test_landscape_preview_does_not_contact_tablet(self):
        with (
            patch.object(dashboard, "get_weather") as get,
            patch.object(dashboard, "build_image") as build,
            patch.object(dashboard, "push_to_remarkable") as push,
        ):
            self.assertEqual(dashboard.main(["--preview", "--orientation", "landscape"]), 0)
        build.assert_called_once_with(get.return_value, orientation="landscape")
        push.assert_not_called()

    def test_overlay_action_requires_explicit_flag(self):
        with (
            patch.object(dashboard, "get_weather"),
            patch.object(dashboard, "build_image"),
            patch.object(dashboard, "push_to_remarkable") as push,
        ):
            self.assertEqual(dashboard.main(["--disable-sleep-overlay"]), 0)
        push.assert_called_once_with(overlay_action="disable")

    def test_upload_failure_returns_nonzero(self):
        with (
            patch.object(dashboard, "get_weather"),
            patch.object(dashboard, "build_image"),
            patch.object(dashboard, "push_to_remarkable",
                         side_effect=subprocess.CalledProcessError(1, "scp")),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(dashboard.main([]), 1)
        self.assertIn("Tablet update failed", stderr.getvalue())


class UploadTests(unittest.TestCase):
    def test_unreachable_tablet_raises_without_remount_or_upload(self):
        with (
            patch.object(dashboard.subprocess, "run") as run,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            run.return_value.returncode = 255
            run.return_value.stderr = b"Connection refused"
            with self.assertRaises(subprocess.CalledProcessError):
                dashboard.push_to_remarkable()
        run.assert_called_once()
        self.assertIn("Connection refused", stderr.getvalue())

    def test_upload_failure_still_remounts_root_read_only(self):
        failure = subprocess.CalledProcessError(1, "scp")
        with patch.object(dashboard.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.side_effect = [run.return_value, run.return_value, failure, run.return_value]
            with self.assertRaises(subprocess.CalledProcessError):
                dashboard.push_to_remarkable()
        self.assertEqual(run.call_args.args[0],
                         ["ssh", dashboard.SSH_HOST, "mount -o remount,ro /"])

    def test_overlay_changes_are_opt_in_and_restore_read_only_mount(self):
        with (
            patch.object(dashboard.subprocess, "run") as run,
            patch.object(dashboard, "set_sleep_overlay") as overlay,
        ):
            run.return_value.returncode = 0
            dashboard.push_to_remarkable()
            overlay.assert_not_called()
            dashboard.push_to_remarkable(overlay_action="disable")
            overlay.assert_called_once_with("disable")
        self.assertEqual(run.call_args.args[0],
                         ["ssh", dashboard.SSH_HOST, "mount -o remount,ro /"])

    def test_overlay_commands_use_reversible_backup_and_exact_asset_names(self):
        for action in ("disable", "restore"):
            with self.subTest(action=action):
                with patch.object(dashboard.subprocess, "run") as run:
                    dashboard.set_sleep_overlay(action)
                command = run.call_args.args[0][2]
                self.assertIn("cd /usr/share/remarkable/carousel", command)
                self.assertIn("dashboard-backup", command)
                self.assertIn("Refusing to overwrite", command)
                self.assertIn("sleep_Illustration_01.png sleep_Illustration_02.png sleep_Illustration_03.png", command)
                self.assertNotIn("rm ", command)


class BuildImageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.photos_dir = self.root / "photos"
        self.output_path = self.root / "dashboard.png"
        self.weather = {
            "temp": 18,
            "humidity": 55,
            "condition": "Partly Cloudy",
            "high": 22,
            "low": 12,
            "forecast": FORECAST,
        }
        self.paths = patch.multiple(
            dashboard,
            PHOTOS_DIR=str(self.photos_dir),
            OUTPUT_PATH=str(self.output_path),
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def test_uses_a_photo_and_writes_paper_pro_sized_png(self):
        self.photos_dir.mkdir()
        Image.new("RGB", (40, 30), (200, 30, 20)).save(self.photos_dir / "photo.png")

        dashboard.build_image(self.weather)

        with Image.open(self.output_path) as result:
            self.assertEqual(result.size, (1620, 2160))
            self.assertEqual(result.format, "PNG")
            self.assertEqual(result.mode, "RGB")
            self.assertEqual(result.getpixel((1500, 1400)), (200, 30, 20))
            self.assertEqual(result.getpixel((1100, 700)), (230, 154, 149))
            self.assertEqual(result.getpixel((100, 2040)), (230, 154, 149))
            self.assertNotEqual(
                result.crop((140, 108, 1050, 680)).getextrema(),
                ((255, 255), (255, 255), (255, 255)),
            )

    def test_missing_photos_folder_uses_placeholder_instead_of_failing(self):
        dashboard.build_image(self.weather)

        with Image.open(self.output_path) as result:
            self.assertEqual(result.size, (1620, 2160))
            self.assertEqual(result.getpixel((0, 0)), (232, 238, 242))

    def test_landscape_rotates_wide_layout_into_portrait_sized_png(self):
        with patch.object(dashboard, "datetime") as clock:
            clock.now.return_value.strftime.side_effect = lambda fmt: {
                "%A, %b %d": "Thursday, Nov 12", "%H:%M": "15:00",
            }[fmt]
            with patch.multiple(dashboard, WIDTH=2160, HEIGHT=1620):
                dashboard.build_image(self.weather)
            with Image.open(self.output_path) as wide:
                expected = wide.transpose(Image.Transpose.ROTATE_270)
            dashboard.build_image(self.weather, orientation="landscape")
        with Image.open(self.output_path) as result:
            self.assertEqual(result.size, (1620, 2160))
            self.assertIsNone(ImageChops.difference(result, expected).getbbox())

    def test_longest_weather_condition_fits_panel(self):
        self.weather["condition"] = "Thunderstorm with Heavy Hail"
        dashboard.build_image(self.weather)
        with Image.open(self.output_path) as result:
            self.assertEqual(result.getpixel((1441, 430)), (232, 238, 242))

    def test_renders_all_seven_rows_and_exact_contact_text_in_both_orientations(self):
        original_text = dashboard.ImageDraw.ImageDraw.text
        for orientation in ("portrait", "landscape"):
            with self.subTest(orientation=orientation):
                with patch.object(dashboard.ImageDraw.ImageDraw, "text", autospec=True,
                                  side_effect=original_text) as text:
                    dashboard.build_image(self.weather, orientation=orientation)
                calls = [(call.args[1], call.args[2]) for call in text.call_args_list]
                for day in FORECAST:
                    self.assertIn(((140, 790 + FORECAST.index(day) * 64),
                                   day["date"].strftime("%a, %b %d")), calls)
                contact_calls = [pos for pos, value in calls
                                 if value == TEST_SETTINGS["CONTACT_INFO"]]
                self.assertEqual(len(contact_calls), 1)
                height = 1620 if orientation == "landscape" else 2160
                self.assertGreater(contact_calls[0][1], height - 140)

    def test_missing_additional_forecast_is_rejected(self):
        self.weather["forecast"] = FORECAST[:6]
        with self.assertRaisesRegex(ValueError, "seven additional"):
            dashboard.build_image(self.weather)

    def test_invalid_orientation_is_rejected(self):
        with self.assertRaises(ValueError):
            dashboard.build_image(self.weather, orientation="automatic")


if __name__ == "__main__":
    unittest.main()
