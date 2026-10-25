#!/usr/bin/env bash
# Regenerates the committed background-movie fixtures with ffmpeg:
#   make_bgmovie_fixtures.sh <output-dir>
# The tests read the committed files; nothing runs this at test time.
# Every movie is 4 frames of mandelbrot (each frame differs), 32x24 at 10 fps.
# The width is a multiple of 4 because ffmpeg writes raw rows unpadded.
set -euo pipefail
out=${1:?usage: make_bgmovie_fixtures.sh <output-dir>}
mkdir -p "$out"
src="mandelbrot=size=32x24:rate=10"
enc() { # name, ffmpeg output args...
  local name=$1; shift
  ffmpeg -v error -y -f lavfi -i "$src" -frames:v 4 "$@" "$out/$name.avi"
}
enc raw24_topdown -c:v rawvideo -pix_fmt bgr24
enc raw24_bottomup -c:v rawvideo -pix_fmt bgr24 -flipped_raw_rgb 1
enc raw32_topdown -c:v rawvideo -pix_fmt bgra
enc mjpeg -c:v mjpeg -q:v 3
enc mpeg4 -c:v mpeg4
enc h264 -c:v libx264
# Reference decodes: per-frame md5 of RGB24 for the exact comparisons, and the
# raw RGB24 frames of the MJPEG file for the tolerance comparison.
for n in raw24_topdown raw24_bottomup raw32_topdown mjpeg; do
  ffmpeg -v error -y -i "$out/$n.avi" -pix_fmt rgb24 -f framemd5 "$out/$n.framemd5"
done
ffmpeg -v error -y -i "$out/mjpeg.avi" -pix_fmt rgb24 -f rawvideo "$out/mjpeg.rgb24"
# Pictures from the first raw frame; reference decodes as above. The alpha
# PNG has a constant alpha of 128.
ffmpeg -v error -y -i "$out/raw24_topdown.avi" -frames:v 1 -update 1 "$out/picture.bmp"
ffmpeg -v error -y -i "$out/raw24_topdown.avi" -frames:v 1 -update 1 "$out/picture.png"
ffmpeg -v error -y -i "$out/raw24_topdown.avi" -frames:v 1 -update 1 "$out/picture.tga"
ffmpeg -v error -y -i "$out/raw24_topdown.avi" -frames:v 1 -update 1 -q:v 3 "$out/picture.jpg"
ffmpeg -v error -y -i "$out/raw24_topdown.avi" -frames:v 1 -update 1 \
  -vf "format=rgba,colorchannelmixer=aa=0.5" "$out/picture_alpha.png"
for n in picture.bmp picture.png; do
  ffmpeg -v error -y -i "$out/$n" -pix_fmt rgb24 -f framemd5 "$out/$n.framemd5"
done
ffmpeg -v error -y -i "$out/picture_alpha.png" -pix_fmt rgba -f framemd5 "$out/picture_alpha.png.framemd5"
ffmpeg -v error -y -i "$out/picture.jpg" -pix_fmt rgb24 -f rawvideo "$out/picture.jpg.rgb24"
