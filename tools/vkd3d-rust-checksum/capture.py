#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Recapture checksum fixtures from the actual hash-pinned vkd3d 2.1 source."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/vkd3d-rust-checksum/native.tsv"
URL = "https://dl.winehq.org/vkd3d/source/vkd3d-2.1.tar.xz"
ARCHIVE_SHA256 = "7510146aff2adfb4ae07ab890701a607e5ff7c66e57100cfc9f630ec92eeda6a"
SOURCE_HASHES = {
    "libs/vkd3d-shader/checksum.c": "4f44212d7a29417583d3b89728e28c597ade13f883227cf1ed21644252a02a13",
    "include/private/vkd3d_common.h": "3d2d4688656a633a20cabff7452cf2922ddbaa1bdd2034697b017c8304d9af7a",
    "libs/vkd3d-shader/vkd3d_shader_private.h": "775dfb70aba299ed2371ddf6623d90298a304aea63a68c4f93ae8db1d44c70fa",
}


def xorshift_bytes(seed, size):
    data = bytearray()
    for _ in range(size):
        seed ^= (seed << 13) & 0xffffffff
        seed ^= seed >> 17
        seed ^= (seed << 5) & 0xffffffff
        data.append(seed & 0xff)
    return data


def cases():
    lengths = list(range(130)) + [191, 192, 193, 255, 256, 257, 511, 512, 513, 1023, 1024, 1025, 4096, 4097]
    state = 0x12345678
    for _ in range(256):
        state = (1664525 * state + 1013904223) & 0xffffffff
        lengths.append(128 + state % 8065)
    return [((0x9e3779b9 * (i + 1)) & 0xffffffff, size) for i, size in enumerate(lengths)]


def checked_source(source):
    texts = {}
    for name, expected in SOURCE_HASHES.items():
        data = (source / name).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"{name}: SHA-256 {actual}, expected {expected}")
        texts[name] = data.decode()
    return texts


def source_header(texts):
    common = texts["include/private/vkd3d_common.h"]
    private = texts["libs/vkd3d-shader/vkd3d_shader_private.h"]
    helpers = []
    for name in ("vkd3d_make_u16", "vkd3d_make_u32"):
        helpers.append(re.search(r"static inline uint\d+_t " + name + r"\([^}]+\n\}", common).group())
    enum = re.search(r"enum vkd3d_md5_variant\n\{[^}]+\};", private).group()
    prototype = re.search(r"void vkd3d_compute_md5\([^;]+;", private).group()
    return "\n".join(["#include <stdint.h>", "#include <stddef.h>", "#include <string.h>",
                      "#define STATIC_ASSERT(x) _Static_assert(x, #x)", *helpers, enum, prototype, ""])


def run(args, log):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    with log.open("a") as output:
        output.write(f"$ {args!r}\n{result.stdout}\nexit {result.returncode}\n")
    result.check_returncode()
    return result.stdout


def capture(args):
    if sys.byteorder != "little" or sys.maxsize <= 2**32:
        raise RuntimeError("The native oracle requires a supported little-endian 64-bit host")
    args.output.mkdir(parents=True, exist_ok=True)
    log = args.output / "native.log"
    log.write_text("")
    assert xorshift_bytes(1, 4).hex() == "2101c54f"
    assert len(cases()) == 400
    with tempfile.TemporaryDirectory(prefix="mds-vkd3d-checksum-") as directory:
        work = Path(directory)
        if args.source_dir:
            source = args.source_dir
        else:
            archive = work / "vkd3d-2.1.tar.xz"
            with urllib.request.urlopen(URL, timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
                raise ValueError("vkd3d 2.1 archive SHA-256 mismatch")
            source = work / "source"
            for name in SOURCE_HASHES:
                with tarfile.open(archive) as tar:
                    data = tar.extractfile(f"vkd3d-2.1/{name}").read()
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        texts = checked_source(source)
        shutil.copyfile(source / "libs/vkd3d-shader/checksum.c", work / "checksum.c")
        (work / "vkd3d_shader_private.h").write_text(source_header(texts))
        compiler = os.environ.get("CC", "cc")
        run([compiler, "--version"], log)
        executable = work / "oracle"
        run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-strict-aliasing",
             "-I", str(work), str(work / "checksum.c"), str(Path(__file__).with_name("oracle.c")),
             "-o", str(executable)], log)
        lines = ["# vkd3d 2.1 checksum.c, little-endian digest bytes; xorshift32 input generator",
                 "# seed\tsize\tstandard\tdxbc"]
        for seed, size in cases():
            data = xorshift_bytes(seed, size)
            path = work / "input.bin"
            path.write_bytes(data)
            digests = run([str(executable), str(path)], log).strip().split("\t")
            if len(digests) != 2 or any(not re.fullmatch(r"[0-9a-f]{32}", d) for d in digests):
                raise ValueError(f"Invalid native digests for {seed:x}/{size}: {digests}")
            if digests[0] != hashlib.md5(data, usedforsecurity=False).hexdigest():
                raise ValueError(f"Native standard MD5 disagrees with hashlib for {seed:x}/{size}")
            lines.append(f"{seed:08x}\t{size}\t{digests[0]}\t{digests[1]}")
        captured = "\n".join(lines) + "\n"
        (args.output / "native.tsv").write_text(captured)
        (args.output / "source.json").write_text(json.dumps({"url": URL, "archive_sha256": ARCHIVE_SHA256,
            "sources": SOURCE_HASHES, "cases": 400, "native_calls": 1600,
            "size_truncation": "Every case also uses a native size_t of 2^32 + actual_size"}, indent=2) + "\n")
        if args.write_fixture:
            FIXTURE.write_text(captured)
        elif captured != FIXTURE.read_text():
            raise ValueError(f"Native fixture changed; compare {args.output / 'native.tsv'} with {FIXTURE}")
    print("PASS: 400 native cases, both variants, 1600 calls including synthetic size truncation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Use a local hash-verified vkd3d 2.1 source tree")
    parser.add_argument("--output", required=True, type=Path, help="Directory for logs and candidate fixtures")
    parser.add_argument("--write-fixture", action="store_true", help="Replace the committed fixture after a deliberate recapture")
    capture(parser.parse_args())
