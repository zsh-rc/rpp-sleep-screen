import argparse
import hashlib
import json
import math
import os
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1620, 2160
WEATHER_CODES = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing Rime Fog", 51: "Light Drizzle",
    53: "Moderate Drizzle", 55: "Dense Drizzle", 56: "Light Freezing Drizzle",
    57: "Dense Freezing Drizzle", 61: "Slight Rain", 63: "Moderate Rain",
    65: "Heavy Rain", 66: "Light Freezing Rain", 67: "Heavy Freezing Rain",
    71: "Slight Snow", 73: "Moderate Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Rain Showers", 81: "Moderate Rain Showers", 82: "Violent Rain Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers", 95: "Thunderstorm",
    96: "Thunderstorm with Hail", 99: "Thunderstorm with Heavy Hail",
}


def load_settings(environ):
    settings = {}
    for name, limit in (("LATITUDE", 90), ("LONGITUDE", 180)):
        value = float(environ[name])
        if not math.isfinite(value) or not -limit <= value <= limit:
            raise ValueError(f"Invalid {name}")
        settings[name] = value
    settings["CITY_NAME"] = environ["CITY_NAME"].strip()
    if not settings["CITY_NAME"]:
        raise ValueError("CITY_NAME must not be empty")
    settings["CONTACT_INFO"] = environ.get("CONTACT_INFO", "").strip()
    return settings


def get_weather(settings):
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": settings["LATITUDE"], "longitude": settings["LONGITUDE"],
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 8, "timezone": "auto",
        },
        timeout=(10, 30),
    )
    response.raise_for_status()
    data = response.json()
    current, daily = data["current"], data["daily"]
    for field in ("time", "weather_code", "temperature_2m_max", "temperature_2m_min"):
        if len(daily[field]) != 8:
            raise ValueError(f"Expected eight forecast days for {field}")
    forecast = [
        {
            "date": date.fromisoformat(daily["time"][index]),
            "condition": WEATHER_CODES.get(daily["weather_code"][index], "Unknown"),
            "high": round(daily["temperature_2m_max"][index]),
            "low": round(daily["temperature_2m_min"][index]),
        }
        for index in range(8)
    ]
    return {
        "temp": round(current["temperature_2m"]),
        "humidity": current["relative_humidity_2m"],
        "condition": WEATHER_CODES.get(current["weather_code"], "Unknown"),
        "high": forecast[0]["high"], "low": forecast[0]["low"],
        "forecast": forecast[1:], "timezone": data["timezone"],
        "weather_time": current["time"],
    }


def load_font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/Library/Fonts") / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    helvetica = Path("/System/Library/Fonts/Helvetica.ttc")
    if helvetica.is_file():
        return ImageFont.truetype(str(helvetica), size=size, index=1 if bold else 0)
    return ImageFont.load_default(size=size)


def fit_font(draw, text, size, maximum_width, bold=False):
    for candidate_size in range(size, 19, -1):
        font = load_font(candidate_size, bold)
        bounds = draw.textbbox((0, 0), text, font=font)
        if bounds[2] - bounds[0] <= maximum_width:
            return font
    raise ValueError(f"Text does not fit: {text}")


def build_image(weather, settings, photos_dir, orientation="portrait", now=None):
    if orientation not in ("portrait", "landscape"):
        raise ValueError("Unsupported orientation")
    if len(weather["forecast"]) != 7:
        raise ValueError("Expected seven additional forecast days")
    width, height = (HEIGHT, WIDTH) if orientation == "landscape" else (WIDTH, HEIGHT)
    photos = sorted(
        path for path in Path(photos_dir).iterdir()
        if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    )
    if not photos:
        raise ValueError(f"No photos found in {photos_dir}; refusing to publish a blank background")
    with Image.open(random.choice(photos)) as photo:
        image = ImageOps.fit(
            ImageOps.exif_transpose(photo).convert("RGB"), (width, height),
            Image.Resampling.LANCZOS,
        )
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    left, top, panel_width, panel_height = 60, 60, 1380, 1240
    footer_top = height - 140
    overlay_draw.rounded_rectangle(
        (left, top, left + panel_width, top + panel_height),
        radius=28, fill=(255, 255, 255, 140),
    )
    overlay_draw.rounded_rectangle(
        (60, footer_top, width - 60, height - 50),
        radius=20, fill=(255, 255, 255, 140),
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((left + 40, top + 36, left + 48, top + panel_height - 36), fill="#1D4ED8")
    text_x = left + 80
    local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(weather["timezone"]))
    heading = f"{settings['CITY_NAME']}  \u2022  {local_now.strftime('%A, %b %d').upper()}"
    draw.text((text_x, top + 48), heading, fill="#475569",
              font=fit_font(draw, heading, 36, panel_width - 120, True))
    draw.text((text_x - 5, top + 100), f"{weather['temp']}\u00b0C",
              fill="#0F172A", font=load_font(170, True))
    draw.text((text_x, top + 320), weather["condition"], fill="#1E293B",
              font=fit_font(draw, weather["condition"], 56, panel_width - 120, True))
    details = (f"H: {weather['high']}\u00b0   L: {weather['low']}\u00b0   "
               f"Humidity: {weather['humidity']}%")
    draw.text((text_x, top + 420), details, fill="#475569", font=load_font(36))
    draw.text((text_x, top + 510), "Today's forecast", fill="#475569", font=load_font(32))
    draw.text((text_x, top + 575), f"Updated {local_now.strftime('%H:%M %Z')}",
              fill="#64748B", font=load_font(30))
    draw.text((text_x, top + 665), "NEXT 7 DAYS", fill="#475569", font=load_font(32, True))
    for index, day in enumerate(weather["forecast"]):
        row_y = top + 730 + index * 64
        draw.text((text_x, row_y), day["date"].strftime("%a, %b %d"),
                  fill="#1E293B", font=load_font(30, True))
        draw.text((text_x + 260, row_y), day["condition"], fill="#1E293B",
                  font=fit_font(draw, day["condition"], 30, 570))
        temperatures = f"H: {day['high']}\u00b0  L: {day['low']}\u00b0"
        draw.text((text_x + 880, row_y), temperatures, fill="#475569",
                  font=fit_font(draw, temperatures, 30, panel_width - 1000))
    contact = settings["CONTACT_INFO"]
    contact_font = fit_font(draw, contact, 36, width - 160, True)
    bounds = draw.textbbox((0, 0), contact, font=contact_font)
    draw.text(((width - bounds[2] + bounds[0]) // 2 - bounds[0], footer_top + 25),
              contact, fill="#0F172A", font=contact_font)
    if orientation == "landscape":
        image = image.transpose(Image.Transpose.ROTATE_270)
    return image


def publish(image, output_dir, weather, orientation):
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    temporary = output_dir / "dashboard.tmp.png"
    image.save(temporary, "PNG")
    with Image.open(temporary) as check:
        check.verify()
    with Image.open(temporary) as check:
        check.load()
        if check.size != (WIDTH, HEIGHT) or check.mode != "RGB":
            raise ValueError("Output must be an opaque 1620 x 2160 RGB PNG")
    checksum = hashlib.sha256(temporary.read_bytes()).hexdigest()
    relative_path = f"images/{checksum}.png"
    temporary.replace(output_dir / relative_path)
    metadata = {
        "schema_version": 1, "sha256": checksum, "image": relative_path,
        "width": WIDTH, "height": HEIGHT, "orientation": orientation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weather_time": weather["weather_time"], "timezone": weather["timezone"],
    }
    (output_dir / "latest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    manifest = output_dir / "latest.tmp"
    manifest.write_text(f"{checksum}  {relative_path}\n", encoding="ascii")
    manifest.replace(output_dir / "latest.sha256")
    (output_dir / ".nojekyll").touch()
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a v2 dashboard for static publication; no tablet access.")
    parser.add_argument("--photos-dir", type=Path, default=ROOT / "photos")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "v2" / "public")
    parser.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(os.environ)
        weather = get_weather(settings)
        image = build_image(weather, settings, args.photos_dir, args.orientation)
        metadata = publish(image, args.output_dir, weather, args.orientation)
    except requests.RequestException as error:
        print(f"Weather request failed ({type(error).__name__}); nothing published. "
              "Check api.open-meteo.com connectivity and HTTPS_PROXY/CA settings. "
              "Requests does not evaluate PAC files.", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError, OSError) as error:
        print(f"Dashboard generation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())