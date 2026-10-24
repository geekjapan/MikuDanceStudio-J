#!/bin/sh
set -eu
apt-get update -qq >/dev/null && apt-get install -y -qq clang >/dev/null
export CARGO_TARGET_DIR=/work/target-$(uname -m)
for mode in plain det; do
  extra=""; [ $mode = det ] && extra="-include /proto/shim/det_math.h"
  out=/work/out-$(uname -m)-$mode; rm -rf $out
  BULLET_SRC=/bullet/src CXX=clang++ sh /proto/build_bullet.sh $out $extra
  cp -r /proto/rs /work/rs-$mode 2>/dev/null || true
  (cd /work/rs-$mode && BT_LIB_DIR=$out cargo build --release -q)
  mkdir -p /work/run-$(uname -m)-$mode && cd /work/run-$(uname -m)-$mode && $CARGO_TARGET_DIR/release/bt-proto && cd /
done
