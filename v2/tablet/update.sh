#!/bin/sh
set -eu
umask 077

: "${BASE_URL:?Set BASE_URL to the HTTPS Pages URL without a trailing slash}"
case "$BASE_URL" in
    https://*) ;;
    *) echo "BASE_URL must use HTTPS" >&2; exit 1 ;;
esac
BASE_URL=${BASE_URL%/}
STATE_DIR=${STATE_DIR:-/home/root/rpp-sleep-screen-v2/state}
TARGET_PATH=${TARGET_PATH:-/usr/share/remarkable/suspended.png}

for tool in curl sha256sum od tr awk flock mktemp mount cp mv rm wc date dirname chmod mkdir; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Missing required tool: $tool" >&2; exit 1; }
done
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/update.lock"
flock -n 9 || exit 0
work=$(mktemp -d "$STATE_DIR/download.XXXXXX")
target_temp="$(dirname "$TARGET_PATH")/.dashboard-v2.new"
restore_ro=0
target_pending=0

cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    if [ "$target_pending" = 1 ]; then
        rm -f "$target_temp" || result=1
    fi
    if [ "$restore_ro" = 1 ]; then
        if ! mount -o remount,ro /; then
            echo "CRITICAL: could not restore root filesystem read-only" >&2
            result=1
        fi
    fi
    rm -rf "$work" || result=1
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

fetch() {
    curl --proto '=https' --proto-redir '=https' --location --fail --silent --show-error \
        --connect-timeout 5 --max-time 20 --max-filesize "$3" --output "$2" "$1"
}

fetch "$BASE_URL/latest.sha256?check=$(date +%s)" "$work/latest.sha256" 256
[ "$(wc -l < "$work/latest.sha256" | tr -d ' ')" = 1 ] || { echo "Invalid manifest" >&2; exit 1; }
IFS=' ' read -r expected image_path extra < "$work/latest.sha256"
case "$expected" in
    ''|*[!0-9a-f]*) echo "Invalid checksum" >&2; exit 1 ;;
esac
[ "${#expected}" = 64 ] && [ "$image_path" = "images/$expected.png" ] && [ -z "$extra" ] || {
    echo "Invalid image path or manifest" >&2; exit 1;
}
if [ -f "$TARGET_PATH" ]; then
    installed=$(sha256sum "$TARGET_PATH")
    if [ "${installed%% *}" = "$expected" ]; then
        echo "Dashboard already current"
        exit 0
    fi
fi

fetch "$BASE_URL/$image_path" "$work/image.png" 20971520
actual=$(sha256sum "$work/image.png")
[ "${actual%% *}" = "$expected" ] || { echo "Image checksum mismatch" >&2; exit 1; }
header=$(od -An -tx1 -N26 "$work/image.png" | tr -d ' \n')
[ "$header" = 89504e470d0a1a0a0000000d4948445200000654000008700802 ] || {
    echo "Expected a 1620 x 2160, 8-bit RGB PNG" >&2; exit 1;
}
if [ ! -f "$STATE_DIR/original-suspended.png" ] && [ -f "$TARGET_PATH" ]; then
    cp "$TARGET_PATH" "$work/original.png"
    mv "$work/original.png" "$STATE_DIR/original-suspended.png"
fi
root_options=$(awk '$2 == "/" { print $4; exit }' /proc/mounts)
case ",$root_options," in
    *,ro,*) mount -o remount,rw /; restore_ro=1 ;;
    *,rw,*) ;;
    *) echo "Cannot determine root mount state" >&2; exit 1 ;;
esac
target_pending=1
cp "$work/image.png" "$target_temp"
chmod 644 "$target_temp"
mv -f "$target_temp" "$TARGET_PATH"
target_pending=0
echo "Sleep screen updated; it will be used on the next sleep if firmware reloads the asset"