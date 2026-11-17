# Dashboard v3 - AppLoad

This is the AppLoad/XOVI alternative to the existing Oxide prototype. It runs
the frontend inside AppLoad, uses a small C++ backend to invoke the existing v2
updater, and displays the installed image without putting the tablet to sleep.
The existing GitHub Actions, GitHub Pages, v2 timer, configuration, target, and
lock remain the single source of truth.

**Status: initial device testing, with known risks.** On one Paper Pro running
firmware 3.29.1.0 / OS 6.0.112, Dashboard opened in AppLoad, showed the image,
and its controls and unchanged-image Refresh worked. A timer-installed image
updated the preview and appeared on the next sleep; the timer ran after reboot.
The test does not establish general firmware compatibility or eliminate the
upstream crash risk. Manual Refresh installing a changed image and the remaining
acceptance checks below have not yet been verified on hardware.

On that device AppLoad did not start automatically after reboot. The user
restored it with reManager's **Modes > Start**; Dashboard then reappeared.
This is an observed workaround, not a guarantee for other installations.

**Root filesystem risk:** During the timer-installed image test, the image was
installed but the updater failed to remount root read-only, leaving it writable.
After a normal reboot root was read-only again. The cause remains unknown and
the issue can recur on either timer or manual installation. Review the
[v2 recovery guidance](../v2/README.md#root-remount-failure) before use.

The backend and QML resource were built with the official Paper Pro firmware
3.29.1.0 / OS 6.0.112 ARM64-host SDK, producing a Linux aarch64 executable.

**Upstream stability risk:** [AppLoad issue #82](https://github.com/asivery/rm-appload/issues/82)
reports that a backend disconnect racing with frontend close can crash
Xochitl. A report reproduces it with AppLoad 0.6.0 on Paper Pure firmware
3.29.1.0; Paper Pro behavior has not been established. A proposed
[fix](https://github.com/asivery/rm-appload/pull/84) is not merged. This
prototype avoids explicitly terminating its backend on normal frontend close,
but that does not eliminate all disconnect or crash risks. Confirm the
upstream fix and compatible release before deploying if avoiding that risk.

## Prerequisites and risks

- Paper Pro with Developer Mode and a working v2 setup; sync/back up documents.
- A compatible XOVI installation, AppLoad and AppLoad's `qt-resource-rebuilder`
  dependency. Confirm the exact versions work together on your firmware before
  installing them. Follow upstream installation and recovery instructions:
  [XOVI](https://github.com/asivery/xovi),
  [AppLoad](https://github.com/asivery/rm-appload), and
  [resource rebuilder](https://github.com/asivery/rm-xovi-extensions).
  Installing these modifies Xochitl startup; it is not done by this project.
- A Linux build host and matching Paper Pro `ferrari` SDK, as described in
  [Build for Paper Pro](./README.md#build-for-paper-pro).
- Keep an independent recovery route and USB SSH access available. Firmware
  upgrades can remove v2's system files or break XOVI/AppLoad hooks.

Before deploying Dashboard, verify that XOVI and AppLoad work on their own:
open the AppLoad menu and run an upstream example, then confirm normal document
use, sleep and wake still work. Do not install Oxide for this frontend.

## Architecture

```text
AppLoad menu -> QML frontend <-> Unix socket <-> dashboard-appload backend
                                                   |
                                       shared v2 updater and lock
                                                   |
                                  GitHub Pages -> installed sleep PNG
```

AppLoad loads `resources.rcc` and starts `backend/entry` with a socket path.
The backend sends state and starts the same v2 updater with `REPORT_STATUS=1`.
It fully decodes the target image before asking the frontend to display the
local file. Pressing **Refresh** checks Pages; it does not start generation.
The image itself contains the weather update time.

- If another update owns the lock, the app displays a busy message.
- Download or validation failures before installation retain the previous image.
  A cleanup failure can occur after the new image was installed and is reported
  as a failure even though the target may have changed.
- **Full screen** hides controls; tap the image to show them. **Back** closes
  the frontend. The backend remains running under AppLoad so that closing the
  frontend during a transfer does not terminate the updater. Reopening the app
  reuses that backend. It terminates when AppLoad disconnects it; it waits for
  an active updater to finish first.
- The target directory is watched for v2 timer updates. The preview also reads
  the current target on backend startup.
- The local preview loads the target path after verification. A concurrent
  timer update can replace that path; the app reloads when it detects the
  change. Timing, e-ink rendering and gesture handling require further testing.

## Sleep behavior

The AppLoad installation **does not run** `--configure-sleep-screen` and does
not modify `xochitl.conf` or Oxide settings. It continues using v2's existing
`TARGET_PATH`. First confirm the existing v2 image appears when the stock UI
sleeps. After installing AppLoad, verify that the newly downloaded image
appears at the next sleep without restarting Xochitl or rebooting. Firmware
may cache or override sleep assets; behavior on other configurations is unverified.
If it fails, keep the previous setup and investigate before changing settings
or adding a restart workaround.

## Build

Build on Linux with the exact SDK for your device as described in
[v3/README.md](./README.md#build-for-paper-pro). The CMake install step now
produces the following inside `v3/build-tablet/package`:

```text
dashboard-appload                 # Linux aarch64 backend
launch.sh                         # shared v2 configuration wrapper
appload/manifest.json
appload/resources.rcc             # compiled QML frontend
appload/backend/entry             # starts dashboard-appload
```

The package also contains the separate Oxide executable, which AppLoad does
not use. Verify `file v3/build-tablet/package/dashboard-appload` reports Linux
aarch64. The SDK's host `rcc` must be compatible with the Qt version used by
Xochitl/AppLoad on the target. Building on desktop macOS produces only a local
test binary, not a deployable tablet binary.

## Install

Only after verifying v2 and AppLoad independently and reviewing the risks above,
pause the v2 timer and wait until its service and any manual refresh finish.
On the tablet:

```sh
systemctl stop rpp-dashboard-v2.timer
systemctl status rpp-dashboard-v2.service --no-pager
```

Do not continue while the service is active. Back up the existing updater before
replacing it. From the Linux build host, replace `TABLET_IP`:

```sh
ssh root@TABLET_IP 'mkdir -p /home/root/rpp-dashboard-v3 /home/root/xovi/exthome/appload/rpp-dashboard-v3/backend'
scp v2/tablet/update.sh root@TABLET_IP:/home/root/rpp-sleep-screen-v2/update.sh.new
scp v3/build-tablet/package/dashboard-appload v3/build-tablet/package/launch.sh \
  root@TABLET_IP:/home/root/rpp-dashboard-v3/
scp v3/build-tablet/package/appload/manifest.json \
  v3/build-tablet/package/appload/resources.rcc \
  root@TABLET_IP:/home/root/xovi/exthome/appload/rpp-dashboard-v3/
scp v3/build-tablet/package/appload/backend/entry \
  root@TABLET_IP:/home/root/xovi/exthome/appload/rpp-dashboard-v3/backend/
ssh root@TABLET_IP
```

On the tablet:

```sh
(
  set -eu
  backup=/home/root/rpp-sleep-screen-v2/update.sh.pre-v3
  if [ -e "$backup" ]; then
    echo "Backup already exists; verify it before proceeding: $backup" >&2
    exit 1
  fi
  cp -p /home/root/rpp-sleep-screen-v2/update.sh "$backup"
  chmod 755 /home/root/rpp-dashboard-v3/dashboard-appload \
    /home/root/rpp-dashboard-v3/launch.sh \
    /home/root/xovi/exthome/appload/rpp-dashboard-v3/backend/entry
  chmod 600 /home/root/rpp-sleep-screen-v2/update.sh.new
  mv /home/root/rpp-sleep-screen-v2/update.sh.new /home/root/rpp-sleep-screen-v2/update.sh
)
```

If the backup already exists, preserve it and verify it is the intended
rollback copy before proceeding. Do not replace an updater while it is running;
coordinate with the timer and any manual refresh first. After successful
installation, restart the timer with `systemctl start rpp-dashboard-v2.timer`
and verify its status and logs. A reboot may start it automatically.

The backend wrapper loads the existing v2 `config.env`. Use the same absolute
`TARGET_PATH` and `STATE_DIR` for both the timer and the app. Settings must be
valid both as shell assignments and systemd `EnvironmentFile` entries.
The AppLoad menu may require a library reload or a normal restart to discover
the app; use AppLoad's own controls and save work first. No restart is
performed automatically.

## Acceptance and recovery

1. Open Dashboard from AppLoad and confirm the current sleep image appears.
2. Tap Refresh. An unchanged publication should say "Already up to date".
3. Publish a new v2 image, refresh, and confirm the preview changes immediately.
4. Sleep and wake; confirm the new image appears and documents remain usable.
5. Test the v2 timer, offline error, a simultaneous timer update, AppLoad's
   close gesture during a download, reopening the app, and a normal reboot.
6. Confirm the v2 timer still starts and fetches after reboot.

On failure, avoid forcing the app or device off during an active updater.
Close the Dashboard frontend, then follow AppLoad/XOVI's own recovery guidance
if needed. Removing only the Dashboard app directory removes its launcher
registration; do so only when its backend is no longer running. This does not
disable v2 or restore its image. The v2 restoration instructions remain in
[v2/README.md](../v2/README.md).

## Local checks

CTest exercises the shared updater adapter, packet framing with local record
sockets, packaged QML using a mock AppLoad endpoint, and rendered preview
pixels. Tests passed on ARM64 Linux using `SOCK_SEQPACKET` and on macOS using a
datagram socket because macOS does not support Unix seqpacket. Neither test
runs the real XOVI/AppLoad plugin; real interoperability and hardware
acceptance remain separate requirements. CI is configured for Linux; check its
actual result separately.

See the [upstream application format](https://github.com/asivery/rm-appload)
for the protocol and lifecycle contract.
