#!/usr/bin/env bash
# Turn the raw Playwright recordings (.build/demo/raw/*.webm) into the demo videos:
# MP4 (H.264, yuv420p, faststart, 1920x1080) plus a short looping GIF per video for the
# README. Run by `make demo-videos` after the demo scripts. ffmpeg is a tool here, not a
# dependency: FFMPEG=/path/to/ffmpeg to override.
set -euo pipefail

FFMPEG="${FFMPEG:-$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)}"
FFPROBE="${FFPROBE:-$(dirname "$FFMPEG")/ffprobe}"
OUT="${OSP_DEMO_OUT:-.build/demo}"
RAW="$OUT/raw"
[ -x "$FFMPEG" ] || { echo "render.sh: ffmpeg not found (set FFMPEG=...)" >&2; exit 1; }

H264=(-c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -movflags +faststart -an)
# Background behind the phone recording: the participant app's page colour, a shade darker.
PAD_COLOUR="0xE5E7EB"

mp4() { # name: raw/<name>.webm -> <name>.mp4 at 1920x1080
	"$FFMPEG" -y -loglevel error -i "$RAW/$1.webm" \
		-vf "scale=1920:1080:flags=lanczos,fps=30" "${H264[@]}" "$OUT/$1.mp4"
}

gif() { # name start seconds: a looping GIF of <seconds> from <start>, 960 px wide, 10 fps
	local palette="$RAW/$1.palette.png"
	local filters="fps=10,scale=960:-1:flags=lanczos"
	"$FFMPEG" -y -loglevel error -ss "$2" -t "$3" -i "$OUT/$1.mp4" -vf "$filters,palettegen=stats_mode=diff" "$palette"
	"$FFMPEG" -y -loglevel error -ss "$2" -t "$3" -i "$OUT/$1.mp4" -i "$palette" \
		-lavfi "$filters[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" -loop 0 "$OUT/$1.gif"
	rm -f "$palette"
	local size
	size=$(wc -c < "$OUT/$1.gif")
	[ "$size" -le 6000000 ] || { echo "render.sh: $1.gif is $size bytes (over 6 MB)" >&2; exit 1; }
}

duration() { "$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$1"; }

mp4 01-building-a-survey
mp4 02-settings-and-publish

# Video 3: the desktop part, then the phone part centred on a 1920x1080 canvas.
"$FFMPEG" -y -loglevel error -i "$RAW/03-participant-desktop.webm" -i "$RAW/03-participant-phone.webm" \
	-filter_complex "[0:v]scale=1920:1080:flags=lanczos,fps=30,setsar=1[a];\
[1:v]scale=-2:1040:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=$PAD_COLOUR,fps=30,setsar=1[b];\
[a][b]concat=n=2:v=1:a=0[v]" -map "[v]" "${H264[@]}" "$OUT/03-participant.mp4"

if [ -f "$RAW/04-results.webm" ]; then mp4 04-results; fi

# GIFs: an 8 s highlight of each.
gif 01-building-a-survey 20 8
gif 02-settings-and-publish 4 8
gif 03-participant "$(awk "BEGIN{print $(duration "$RAW/03-participant-desktop.webm") + 1}")" 8
if [ -f "$OUT/04-results.mp4" ]; then gif 04-results 3 8; fi

total=0
for f in "$OUT"/0*.mp4; do
	d=$(duration "$f")
	total=$(awk "BEGIN{print $total + $d}")
	printf '%-40s %6.1f s  %s\n' "$(basename "$f")" "$d" "$(du -h "${f%.mp4}.gif" | cut -f1) gif"
done
printf 'total %.1f s\n' "$total"
awk "BEGIN{exit !($total < 360)}" || { echo "render.sh: total over 6 minutes" >&2; exit 1; }
