#!/bin/sh
# usage: build_bullet.sh <out-dir> [extra clang flags]
set -eu
out=$1; shift
src=/Users/geekjapan/dev/projects/MikuDanceStudio-J/recipes/bullet275/bullet-src/src
mkdir -p "$out/obj"
CXX=${CXX:-clang++}
n=0
for f in $(find $src/LinearMath $src/BulletCollision $src/BulletDynamics -name '*.cpp') ${SHIM:-/tmp/proto-bullet/shim/bt_shim.cpp}; do
  n=$((n+1)); o="$out/obj/$n.o"
  $CXX -O2 -ffp-contract=off -fno-fast-math -fdeclspec -w -I$src "$@" -c "$f" -o "$o" &
done; wait
ar rcs "$out/libbtshim.a" "$out"/obj/*.o
