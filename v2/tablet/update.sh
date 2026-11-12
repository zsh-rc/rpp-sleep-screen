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
IMAGE_TIMEOUT=${IMAGE_TIMEOUT:-300}
CHECK_ONLY=${CHECK_ONLY:-0}
case "$IMAGE_TIMEOUT" in
    ''|*[!0-9]*) echo "IMAGE_TIMEOUT must be 1..1800 seconds" >&2; exit 1 ;;
esac
[ "${#IMAGE_TIMEOUT}" -le 4 ] && [ "$IMAGE_TIMEOUT" -ge 1 ] && [ "$IMAGE_TIMEOUT" -le 1800 ] || {
    echo "IMAGE_TIMEOUT must be 1..1800 seconds" >&2; exit 1;
}
case "$CHECK_ONLY" in
    0|1) ;;
    *) echo "CHECK_ONLY must be 0 or 1" >&2; exit 1 ;;
esac

DOWNLOADER=${DOWNLOADER:-auto}
if [ "$DOWNLOADER" = auto ]; then
    if command -v curl >/dev/null 2>&1; then DOWNLOADER=curl; else DOWNLOADER=wget; fi
fi
case "$DOWNLOADER" in
    curl) download_tools=curl ;;
    wget) download_tools='wget openssl timeout cat' ;;
    *) echo "DOWNLOADER must be auto, curl or wget" >&2; exit 1 ;;
esac
for tool in $download_tools sha256sum dd cmp tr awk flock mktemp mount cp mv rm wc date dirname chmod mkdir; do
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
    if [ "$DOWNLOADER" = curl ]; then
        curl --proto '=https' --proto-redir '=https' --location --fail --silent --show-error \
            --connect-timeout 5 --max-time "$4" --max-filesize "$3" --output "$2" "$1"
    else
        block_limit=$(( ($3 + 511) / 512 ))
        if [ "$block_limit" -lt 8 ]; then block_limit=8; fi
        if (
            ulimit -f "$block_limit"
            timeout "$4" wget -T 5 -S -O "$2" "$1"
        ) 2> "$work/wget.log"; then
            if ! awk '
                /^[ \t]*HTTP\/[0-9.]+[ \t]/ { seen++; if ($2 != 200) bad=1 }
                tolower($0) ~ /certificate.*not implemented/ { bad=1 }
                END { exit (bad || seen != 1) }
            ' "$work/wget.log"; then
                echo "Rejecting redirected response or unsupported TLS validation" >&2
                return 1
            fi
        else
            cat "$work/wget.log" >&2
            return 1
        fi
    fi
    downloaded_size=$(wc -c < "$2" | tr -d ' ')
    [ "$downloaded_size" -le "$3" ] || { echo "Download exceeds size limit" >&2; return 1; }
}

fetch "$BASE_URL/latest.sha256?check=$(date +%s)" "$work/latest.sha256" 256 20
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

fetch "$BASE_URL/$image_path" "$work/image.png" 20971520 "$IMAGE_TIMEOUT"
actual=$(sha256sum "$work/image.png")
[ "${actual%% *}" = "$expected" ] || { echo "Image checksum mismatch" >&2; exit 1; }
dd if="$work/image.png" of="$work/header.actual" bs=26 count=1 2>/dev/null
printf '\211PNG\r\n\032\n\000\000\000\015IHDR\000\000\006\124\000\000\010\160\010\002' > "$work/header.expected"
cmp -s "$work/header.actual" "$work/header.expected" || {
    echo "Expected a 1620 x 2160, 8-bit RGB PNG" >&2; exit 1;
}
if [ "$CHECK_ONLY" = 1 ]; then
    echo "Dashboard download verified using $DOWNLOADER; sleep screen unchanged"
    exit 0
fi
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