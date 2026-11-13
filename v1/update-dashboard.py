import argparse
import os
import random
import subprocess
import sys
from datetime import date, datetime
import requests
from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")


def load_configuration(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing configuration: {path}. Copy .env.example to .env first.")
    values = dotenv_values(path, interpolate=False)
    settings = {}
    for name in ("LATITUDE", "LONGITUDE", "CITY_NAME", "SSH_HOST", "CONTACT_INFO"):
        value = values.get(name)
        if value is None or (name != "CONTACT_INFO" and not value.strip()):
            raise ValueError(f"Missing or empty {name} in {path}.")
        settings[name] = value.strip()
    try:
        latitude = float(settings["LATITUDE"])
        longitude = float(settings["LONGITUDE"])
    except ValueError as error:
        raise ValueError("LATITUDE and LONGITUDE must be numbers.") from error
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("LATITUDE must be within -90..90 and LONGITUDE within -180..180.")
    return latitude, longitude, settings["CITY_NAME"], settings["SSH_HOST"], settings["CONTACT_INFO"]


LATITUDE, LONGITUDE, CITY_NAME, SSH_HOST, CONTACT_INFO = load_configuration(
    ENV_PATH
)
# Corporate PAC files are not evaluated by Requests. Set HTTPS_PROXY in your
# terminal to the explicit HTTP/HTTPS proxy address provided by IT.

PHOTOS_DIR = os.path.join(BASE_DIR, "..", "photos")
OUTPUT_PATH = os.path.join(BASE_DIR, "dashboard.png")

WIDTH, HEIGHT = 1620, 2160

# WMO Weather Code mapping
WEATHER_CODES = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing Rime Fog", 51: "Light Drizzle",
    53: "Moderate Drizzle", 55: "Dense Drizzle",
    56: "Light Freezing Drizzle", 57: "Dense Freezing Drizzle",
    61: "Slight Rain",
    63: "Moderate Rain", 65: "Heavy Rain", 71: "Slight Snow",
    66: "Light Freezing Rain", 67: "Heavy Freezing Rain",
    73: "Moderate Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Rain Showers", 81: "Moderate Rain Showers", 82: "Violent Rain Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers", 95: "Thunderstorm",
    96: "Thunderstorm with Hail", 99: "Thunderstorm with Heavy Hail",
}

def get_weather():
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 8,
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    
    current = data["current"]
    daily = data["daily"]
    code = current["weather_code"]
    for field in ("time", "weather_code", "temperature_2m_max", "temperature_2m_min"):
        if len(daily[field]) != 8:
            raise ValueError(f"Expected eight forecast days for {field}.")
    forecast = [
        {
            "date": date.fromisoformat(daily["time"][i]),
            "condition": WEATHER_CODES.get(daily["weather_code"][i], "Unknown"),
            "high": round(daily["temperature_2m_max"][i]),
            "low": round(daily["temperature_2m_min"][i]),
        }
        for i in range(1, 8)
    ]
    
    return {
        "temp": round(current["temperature_2m"]),
        "humidity": current["relative_humidity_2m"],
        "condition": WEATHER_CODES.get(code, "Unknown"),
        "high": round(daily["temperature_2m_max"][0]),
        "low": round(daily["temperature_2m_min"][0]),
        "forecast": forecast,
    }

def load_font(size, bold=False):
    font_path = "/System/Library/Fonts/Helvetica.ttc"
    index = 1 if bold else 0
    try:
        return ImageFont.truetype(font_path, size=size, index=index)
    except OSError as error:
        print(f"Could not load {font_path}: {error}; using Pillow's fallback font.",
              file=sys.stderr)
        return ImageFont.load_default(size=size)

def build_image(weather, orientation="portrait"):
    if orientation not in ("portrait", "landscape"):
        raise ValueError(f"Unsupported orientation: {orientation}")
    width, height = (HEIGHT, WIDTH) if orientation == "landscape" else (WIDTH, HEIGHT)
    if len(weather["forecast"]) != 7:
        raise ValueError("Expected seven additional forecast days.")
    canvas = Image.new("RGB", (width, height), "#E8EEF2")
    draw = ImageDraw.Draw(canvas)

    valid_exts = (".jpg", ".jpeg", ".png", ".webp")
    photos = (
        [f for f in os.listdir(PHOTOS_DIR) if f.lower().endswith(valid_exts)]
        if os.path.isdir(PHOTOS_DIR)
        else []
    )

    if photos:
        chosen = os.path.join(PHOTOS_DIR, random.choice(photos))
        with Image.open(chosen) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            fitted = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)
            canvas.paste(fitted, (0, 0))
    else:
        print(f"No photos found in {PHOTOS_DIR}; using a plain background.")
        draw.text((80, height - 120), "Add photos to the photos folder",
                  fill="#334155", font=load_font(44))

    # Composite translucency locally; keep the tablet PNG fully opaque.
    left, top, panel_width, panel_height = 60, 60, 1380, 1240
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (left, top, left + panel_width, top + panel_height),
        radius=28, fill=(255, 255, 255, 140),
    )
    footer_top = height - 140
    overlay_draw.rounded_rectangle(
        (60, footer_top, width - 60, height - 50),
        radius=20, fill=(255, 255, 255, 140),
    )
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((left + 40, top + 36, left + 48, top + panel_height - 36),
                   fill="#1D4ED8")
    x = left + 80
    now = datetime.now()
    date_str = now.strftime("%A, %b %d").upper()
    updated_str = f"Updated {now.strftime('%H:%M')}"

    draw.text((x, top + 48), f"{CITY_NAME}  •  {date_str}",
              fill="#475569", font=load_font(36, bold=True))
    temp_str = f"{weather['temp']}°C"
    draw.text((x - 5, top + 100), temp_str,
              fill="#0F172A", font=load_font(170, bold=True))

    for size in range(56, 19, -1):
        condition_font = load_font(size, bold=True)
        bounds = draw.textbbox((0, 0), weather["condition"], font=condition_font)
        if bounds[2] - bounds[0] <= panel_width - 120:
            break
    else:
        raise ValueError("Weather condition text does not fit the dashboard panel.")
    draw.text((x, top + 320), weather["condition"],
              fill="#1E293B", font=condition_font)
    details_str = f"H: {weather['high']}°   L: {weather['low']}°   Humidity: {weather['humidity']}%"
    draw.text((x, top + 420), details_str, fill="#475569", font=load_font(36))
    draw.text((x, top + 510), "Today's forecast", fill="#475569", font=load_font(32))
    draw.text((x, top + 575), updated_str, fill="#64748B", font=load_font(30))

    draw.text((x, top + 665), "NEXT 7 DAYS", fill="#475569", font=load_font(32, bold=True))
    for index, day in enumerate(weather["forecast"]):
        y = top + 730 + index * 64
        draw.text((x, y), day["date"].strftime("%a, %b %d"),
                  fill="#1E293B", font=load_font(30, bold=True))
        for size in range(30, 19, -1):
            font = load_font(size)
            bounds = draw.textbbox((0, 0), day["condition"], font=font)
            if bounds[2] - bounds[0] <= 570:
                break
        else:
            raise ValueError("Forecast condition text does not fit the dashboard panel.")
        draw.text((x + 260, y), day["condition"], fill="#1E293B", font=font)
        draw.text((x + 880, y), f"H: {day['high']}°  L: {day['low']}°",
                  fill="#475569", font=load_font(30))

    contact_font = load_font(36, bold=True)
    bounds = draw.textbbox((0, 0), CONTACT_INFO, font=contact_font)
    contact_width = bounds[2] - bounds[0]
    if contact_width > width - 160:
        raise ValueError("Contact information does not fit the footer.")
    draw.text(((width - contact_width) // 2 - bounds[0], footer_top + 25),
              CONTACT_INFO, fill="#0F172A", font=contact_font)

    # The tablet still expects a portrait-sized suspended.png.
    if orientation == "landscape":
        canvas = canvas.transpose(Image.Transpose.ROTATE_270)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    canvas.save(OUTPUT_PATH, "PNG")
    print(f"Generated {OUTPUT_PATH}")

def set_sleep_overlay(action):
    if action not in ("disable", "restore"):
        raise ValueError(f"Unsupported overlay action: {action}")
    source, destination = (
        (".", "dashboard-backup") if action == "disable"
        else ("dashboard-backup", ".")
    )
    command = f"""
set -eu
cd /usr/share/remarkable/carousel
mkdir -p dashboard-backup
for name in sleep_Illustration_01.png sleep_Illustration_02.png sleep_Illustration_03.png; do
    if [ -f "{source}/$name" ]; then
        if [ -e "{destination}/$name" ]; then
            echo "Refusing to overwrite existing overlay file: {destination}/$name" >&2
            exit 1
        fi
    elif [ ! -f "{destination}/$name" ]; then
        echo "Missing expected overlay file: $name" >&2
        exit 1
    fi
done
for name in sleep_Illustration_01.png sleep_Illustration_02.png sleep_Illustration_03.png; do
    if [ -f "{source}/$name" ]; then
        mv "{source}/$name" "{destination}/$name"
    fi
done
"""
    subprocess.run(["ssh", SSH_HOST, command], check=True)


def push_to_remarkable(overlay_action=None):
    # Check if tablet is reachable on Wi-Fi (fails fast if asleep)
    ping = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=4", "-o", "BatchMode=yes", SSH_HOST, "echo ok"],
        capture_output=True
    )
    if ping.returncode != 0:
        print("Tablet SSH check failed. Skipping upload.", file=sys.stderr)
        if ping.stderr:
            print(ping.stderr.decode(errors="replace").strip(), file=sys.stderr)
        raise subprocess.CalledProcessError(ping.returncode, ping.args)

    print("Tablet online. Uploading sleep screen...")
    subprocess.run(["ssh", SSH_HOST, "mount -o remount,rw /"], check=True)
    try:
        subprocess.run(["scp", OUTPUT_PATH, f"{SSH_HOST}:/usr/share/remarkable/suspended.png"], check=True)
        if overlay_action:
            set_sleep_overlay(overlay_action)
    finally:
        subprocess.run(["ssh", SSH_HOST, "mount -o remount,ro /"], check=True)
    print("Sleep screen updated successfully!")
    if overlay_action:
        print(f"Sleep overlay action completed: {overlay_action}. "
              "If the old illustration remains, save your work and reboot the tablet.")

def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate and upload a Paper Pro weather/photo sleep screen.")
    parser.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait",
                        help="Landscape is rotated clockwise into the tablet's portrait-sized PNG.")
    parser.add_argument("--preview", action="store_true", help="Generate the PNG without contacting the tablet.")
    overlays = parser.add_mutually_exclusive_group()
    overlays.add_argument("--disable-sleep-overlay", action="store_const", const="disable", dest="overlay_action",
                          help="Back up the three carousel illustrations so they no longer cover the dashboard.")
    overlays.add_argument("--restore-sleep-overlay", action="store_const", const="restore", dest="overlay_action",
                          help="Restore the backed-up carousel illustrations.")
    args = parser.parse_args(argv)
    if args.preview and args.overlay_action:
        parser.error("Overlay changes require an upload; do not combine them with --preview.")
    try:
        weather_data = get_weather()
    except requests.RequestException as error:
        print(
            f"Weather request failed ({type(error).__name__}). "
            "No dashboard was generated or uploaded. "
            "Check network access to api.open-meteo.com; on a corporate network, "
            "set HTTPS_PROXY to the explicit proxy address provided by IT "
            "(Requests does not evaluate PAC files). "
            "Also check that NO_PROXY does not bypass the required proxy "
            "for api.open-meteo.com.",
            file=sys.stderr,
        )
        return 1
    except (KeyError, TypeError, ValueError) as error:
        print(f"Invalid weather response: {error}. No dashboard was generated or uploaded.",
              file=sys.stderr)
        return 1
    build_image(weather_data, orientation=args.orientation)
    if not args.preview:
        try:
            push_to_remarkable(overlay_action=args.overlay_action)
        except subprocess.CalledProcessError as error:
            print(f"Tablet update failed (exit status {error.returncode}); "
                  "see the SSH/SCP error above.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
