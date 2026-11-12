# reMarkable Paper Pro Dashboard

Generate a photo and weather dashboard on your computer and upload it to the
reMarkable Paper Pro sleep screen.

## Features

- Random photo background, cropped to fill the screen with EXIF rotation applied.
- Current temperature, condition, humidity, and today's high/low temperatures.
- Seven additional forecast days with conditions and high/low temperatures.
- Semi-transparent weather panel and contact footer.
- Portrait or manually selected landscape orientation.
- Optional, reversible removal of the default carousel illustrations.
- Local preview without contacting the tablet.

Weather comes from [Open-Meteo](https://open-meteo.com/en/docs). The output is an
opaque RGB PNG measuring 1620 x 2160 pixels. Panel transparency is blended into
the photo before saving.

## 1. Prepare the Python environment

These instructions target macOS. The project has been tested with Python 3.14
and Pillow 13. It requires `requests`, `Pillow`, and `python-dotenv`; no additional test framework
is needed.

Install Python 3 if necessary. For example, with
[Homebrew](https://brew.sh/):

```bash
brew install python
```

Open a terminal in the project directory, then create and activate a virtual
environment:

```bash
cd /path/to/rpp-dashboard
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If the environment already exists, activate it rather than recreating it:

```bash
source venv/bin/activate
```

Use `python -m pip` so packages are installed into the same environment that
runs the script. Activate the environment again in each new terminal.

The script uses macOS Helvetica fonts. If unavailable, it reports a warning
and uses Pillow's fallback font.

## 2. Prepare tablet SSH access

The Paper Pro requires Developer Mode for SSH access. Follow the
[official Developer Mode instructions](https://support.remarkable.com/s/article/Developer-mode)
and read the reset and security warnings before enabling it. Back up your
documents first.

Find the tablet's SSH username, password, and IP address in its settings under
the copyright/licence information. Menu labels can vary with software versions.
Keep the tablet awake and connect it by USB, or use a reachable Wi-Fi address.
The USB IP commonly used by this project is `10.11.99.1`.

Test the connection, substituting your tablet's IP if different:

```bash
ssh root@10.11.99.1
```

Verify the tablet's host key before accepting the first-connection prompt.
Enter its SSH password when prompted, then run `exit` to disconnect.

### Configure SSH-key authentication

The script's connectivity check uses `BatchMode=yes`, so it cannot prompt for
a password. Set up key authentication before uploading.

If you do not already have a suitable SSH key, create one:

```bash
ssh-keygen -t ed25519
```

Do not overwrite an existing key. If your private key uses a passphrase, load
it into your SSH agent:

```bash
ssh-add ~/.ssh/id_ed25519
```

Install the **public** key on the tablet:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@10.11.99.1
```

If `ssh-copy-id` is unavailable, install it with `brew install ssh-copy-id`.
Never upload or share your private key.

Verify noninteractive access:

```bash
ssh -o ConnectTimeout=4 -o BatchMode=yes root@10.11.99.1 "echo ok"
```

Continue when this prints `ok` without asking for a password.

## 3. Configure the dashboard

Create your local configuration, then edit [.env](./.env):

```bash
cp .env.example .env
```

Do not overwrite an existing `.env` containing your settings.

```dotenv
LATITUDE=31.2304
LONGITUDE=121.4737
CITY_NAME="SHANGHAI"
SSH_HOST="root@10.11.99.1"
CONTACT_INFO="your-email@example.com | your phone number"
```

The script reads `.env` beside the script, independent of the terminal's working
directory. All five variables must be present; `CONTACT_INFO=""` is allowed.
Coordinates must be numeric and within valid latitude/longitude ranges.
Settings are read directly from the file, not overridden by shell environment
variables. Restart the script after editing.

`.env` is ignored by Git. Commit only [.env.example](./.env.example), with
placeholder contact information. Virtual environments, generated dashboards,
local photos, and `IMG_*.png` tablet screenshots are also ignored.

- Set latitude, longitude, and city name to your location.
- Include the SSH username in `SSH_HOST`, or use an alias configured in your
  SSH config with the correct user, hostname, and identity file.
- Change or remove the personal contact text as desired. It is visible to
  anyone who can see the tablet's sleep screen.
- Dates and the update timestamp use the computer's local clock. Forecast
  dates use the location's timezone from Open-Meteo.

Create the photo folder alongside the script and add your own images:

```bash
mkdir -p photos
```

Supported extensions: `.jpg`, `.jpeg`, `.png`, and `.webp` (case-insensitive).
Each run selects one photo randomly. Photos are cropped, not stretched.
If the folder is missing or empty, the script reports this and uses a plain
background. An unreadable or corrupt selected photo causes generation to fail.

The generated [dashboard.png](./dashboard.png) is saved alongside the script
and overwritten on each successful generation.

### Adjust panel transparency

The two white panel fills in `build_image` use `(255, 255, 255, 140)`.
The final number is opacity from `0` (fully transparent) to `255` (fully opaque).
The current value is approximately 55% opacity. Change both values to adjust
the weather panel and contact footer; text stays fully opaque.

## 4. Preview and upload

Run commands from the project directory with the virtual environment active.

### Preview only

```bash
python update-dashboard.py --preview
open dashboard.png
```

Preview still requests live weather but does not contact or modify the tablet.

### Upload portrait

```bash
python update-dashboard.py
```

The script generates the image, checks SSH access, temporarily remounts the
tablet's root filesystem writable, uploads to
`/usr/share/remarkable/suspended.png`, and attempts to remount it read-only in
a `finally` block.

Put the tablet to sleep after a successful upload. If the previous image is
still displayed, save your work and reboot the tablet.

### Upload landscape

```bash
python update-dashboard.py --orientation landscape
```

Landscape is composed as a wide layout, then rotated clockwise into the
portrait-sized PNG expected by the tablet. Hold the tablet accordingly.
This is **not automatic orientation detection**.

To preview landscape without uploading:

```bash
python update-dashboard.py --preview --orientation landscape
```

The saved preview is rotated, just like the uploaded PNG.

### Remove default sleep-screen illustrations

Some Paper Pro firmware versions draw carousel illustrations on top of a
custom background. Uploading the dashboard alone does not remove them.

Run once while the tablet is awake and reachable:

```bash
python update-dashboard.py --disable-sleep-overlay
```

Or combine it with landscape:

```bash
python update-dashboard.py --orientation landscape --disable-sleep-overlay
```

This moves these three files from `/usr/share/remarkable/carousel/` into its
`dashboard-backup/` subfolder:

- `sleep_Illustration_01.png`
- `sleep_Illustration_02.png`
- `sleep_Illustration_03.png`

It does not delete the illustrations and refuses to overwrite existing
destination files. Once the command succeeds, save your work and reboot if
the overlay remains cached. Subsequent uploads do not need the flag.

Restore the illustrations with:

```bash
python update-dashboard.py --restore-sleep-overlay
```

This command also generates and uploads a fresh dashboard. Both overlay
options require live weather and tablet access, cannot be used together, and
cannot be combined with `--preview`.

These system-file customizations are unofficial and may be reset by firmware
updates. The overlay workaround was used with Paper Pro software 3.29.1.0;
other firmware may use different assets. See the
[carousel workaround guide](https://notableutility.com/manual-rmpp).

Display all command options:

```bash
python update-dashboard.py --help
```

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `ModuleNotFoundError` for a dependency | Activate `venv`, then run `python -m pip install -r requirements.txt`. |
| Missing or invalid configuration | Copy `.env.example` to `.env` if missing, then check all five settings and coordinate ranges. |
| Weather connection timeout | Confirm access to `api.open-meteo.com` from the terminal, not only a browser. Check VPN, firewall, and proxy routing. |
| Corporate browser works but Python does not | Requests does not evaluate PAC files. Ask IT for an explicit proxy address if your network requires one. |
| `Permission denied (publickey,password)` | Verify the username, public-key installation, SSH agent, and `BatchMode=yes` test. |
| SSH timeout or connection refused | Wake the tablet, reconnect USB or check Wi-Fi/IP, and confirm Developer Mode is enabled. |
| Default illustration covers the dashboard | Run `--disable-sleep-overlay` successfully, then reboot if needed. |
| Missing overlay files or backup conflict | Read the reported path and inspect it before making changes. Do not delete backups blindly. |
| Old image remains after upload | Save your work and reboot the tablet to clear cached assets. |
| Read-only remount fails | Do not ignore the SSH error. Restore read-only mode with `ssh root@10.11.99.1 "mount -o remount,ro /"` once reachable. |

For a required corporate proxy, an example terminal setting is:

```bash
export HTTPS_PROXY="http://proxy.example.com:8080"
```

Use the actual IT-provided address, not this placeholder. Check that
`NO_PROXY` does not unintentionally bypass the required proxy for the weather
API. Conversely, if direct access is allowed and an obsolete proxy setting
causes failures, correct that setting according to your network policy.
Do not disable TLS certificate verification or put proxy credentials in source
code.

Weather/network failures stop the run without generating or uploading a new
image. A previous local PNG may still exist; it is not evidence that the latest
run succeeded. Failed tablet uploads return a nonzero exit status.

## Tests

Run the offline test suite:

```bash
python -m unittest discover -s tests -v
```

Tests cover forecast parsing, all seven additional days, translucent panels,
contact text, portrait/landscape rendering, command-line behavior, and upload
error handling. Network and tablet operations are mocked; running tests does
not upload anything.

To leave the virtual environment:

```bash
deactivate
```
