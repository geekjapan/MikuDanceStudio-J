#!/bin/sh
set -eu
apt-get update -qq >/dev/null
apt-get install -y -qq build-essential bison flex pkg-config spirv-headers libvulkan-dev spirv-tools xz-utils libjson-perl wine64-tools >/dev/null 2>&1
mkdir -p /work/src && cd /work/src && tar xf /dl/vkd3d-2.1.tar.xz
cd vkd3d-2.1 && (./configure --prefix=/work/vkd3d --disable-tests > /work/configure.log 2>&1 || (tail -20 /work/configure.log; exit 1))
make -j8 > /work/make.log 2>&1 || (tail -30 /work/make.log; exit 1); make -s install >/dev/null 2>&1
/work/vkd3d/bin/vkd3d-compiler --version
cargo install -q naga-cli --root /work/naga 2>&1 | tail -2
/work/naga/bin/naga --version
