#!/bin/sh
set -eu
umask 077

export PATH="/home/root/.vellum/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CONFIG_PATH=${CONFIG_PATH:-/home/root/rpp-sleep-screen-v2/config.env}
[ -f "$CONFIG_PATH" ] || { echo "Missing v2 configuration: $CONFIG_PATH" >&2; exit 1; }
set -a
. "$CONFIG_PATH"
set +a
: "${BASE_URL:?Set BASE_URL in the v2 configuration}"
export TARGET_PATH=${TARGET_PATH:-/usr/share/remarkable/suspended.png}
export STATE_DIR=${STATE_DIR:-/home/root/rpp-sleep-screen-v2/state}
export UPDATER_PATH=${UPDATER_PATH:-/home/root/rpp-sleep-screen-v2/update.sh}
[ -f "$UPDATER_PATH" ] || { echo "Missing updater: $UPDATER_PATH" >&2; exit 1; }

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$app_dir/rpp-dashboard" "$@"
