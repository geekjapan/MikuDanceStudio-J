#!/usr/bin/env python3
"""Write licenses/: the repository's own license files, the texts of what the packages ship
besides mds-app (Bullet 2.75, vkd3d-shader, the AOCL-LibM notice of mds-crtmath, the Rust
standard library), and the license files of every third-party crate in mds-app's dependency
graph, for the three package targets (docs/PACKAGING.md).

Usage: licenses.py [--fetch]

The crates come from `cargo metadata` (features default + dxopenni, normal and build edges, the
targets of TARGETS). A crate's texts are the license files in its package; for a crate whose
package has none, the files from its repository at the commit it was published from
(`.cargo_vcs_info.json`), which `--fetch` downloads into licenses/fetched/ with `gh api`.
Fails when a crate has neither. Needs the vkd3d tarball that tools/vkd3d/build.sh downloads
(MDS_VKD3D_OUT, else ${TMPDIR}/mds-vkd3d). licenses/mingw-runtime/ is written by mingw-copyright.sh
and only checked here.
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "licenses"
TARGETS = ["aarch64-apple-darwin", "x86_64-pc-windows-msvc", "aarch64-unknown-linux-gnu",
           "x86_64-unknown-linux-gnu"]
NAME = re.compile(r"(?i)^(licen[sc]e|copying|notice|copyright|unlicense)")
# Texts a package keeps under other names.
EXTRA = {"epaint_default_fonts": re.compile(r"^fonts/[^/]+\.txt$")}
# Files written here; everything else under licenses/ is left alone.
GENERATED = ["LICENSE", "LICENSE-MIT", "FORK.md", "bullet-2.75", "mds-crtmath", "vkd3d", "rust",
             "crates.tsv", "THIRD-PARTY.txt", "README.md"]


def die(msg):
    sys.exit(f"licenses.py: {msg}")


def graph():
    cmd = ["cargo", "metadata", "--format-version", "1", "--locked", "--features",
           "mds-app/dxopenni"]
    for t in TARGETS:
        cmd += ["--filter-platform", t]
    meta = json.loads(subprocess.run(cmd, cwd=REPO / "rust", check=True,
                                     capture_output=True, text=True).stdout)
    pkgs = {p["id"]: p for p in meta["packages"]}
    nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}
    seen, stack = set(), [next(i for i, p in pkgs.items() if p["name"] == "mds-app")]
    while stack:
        i = stack.pop()
        if i not in seen:
            seen.add(i)
            stack += [d["pkg"] for d in nodes[i]["deps"]
                      if any(k["kind"] in (None, "build") for k in d["dep_kinds"])]
    third = [pkgs[i] for i in seen if pkgs[i]["source"]]
    return sorted(third, key=lambda p: (p["name"], p["version"]))


def package_files(p):
    """The license files in the crate's package, as (relative path, bytes)."""
    root = Path(p["manifest_path"]).parent
    extra = EXTRA.get(p["name"])
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or rel.startswith(("tests/", "target/")) or rel.endswith(".rs"):
            continue
        if NAME.match(path.name) or (extra and extra.match(rel)):
            found.append((rel, path.read_bytes()))
    if p.get("license_file") and not any(r == p["license_file"] for r, _ in found):
        found.append((p["license_file"], (root / p["license_file"]).read_bytes()))
    return found


def fetched_dir(p):
    return OUT / "fetched" / f"{p['name']}-{p['version']}"


def fetched_files(p):
    d = fetched_dir(p)
    if not d.is_dir():
        return []
    # NOTE: written by hand for a crate that publishes no text anywhere.
    return [(f.name, f.read_bytes()) for f in sorted(d.iterdir()) if f.name != "SOURCE"]


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def fetch(p):
    """The license files of the crate's repository at its published commit, nearest to the
    crate's directory there."""
    vcs = Path(p["manifest_path"]).parent / ".cargo_vcs_info.json"
    url = p.get("repository") or ""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#]+?)(?:\.git)?(?:/|$)", url)
    if not vcs.is_file() or not m:
        return f"no .cargo_vcs_info.json or GitHub repository ({url})"
    info = json.loads(vcs.read_text())
    sha, sub = info["git"]["sha1"], info.get("path_in_vcs", "")
    owner, repo = m.groups()
    parts = [s for s in sub.split("/") if s]
    # Some published commits were never pushed; then the release tag.
    v, n = p["version"], p["name"]
    refs = [sha, v, f"v{v}", f"{n}-v{v}", f"{n}-{v}"]
    ref = next((r for r in refs if gh(f"repos/{owner}/{repo}/commits/{r}")), None)
    if not ref:
        return f"github.com/{owner}/{repo} has none of the refs {refs}"
    for depth in range(len(parts), -1, -1):
        d = "/".join(parts[:depth])
        listing = gh(f"repos/{owner}/{repo}/contents/{d}?ref={ref}")
        hits = [e for e in listing or [] if e["type"] == "file" and NAME.match(e["name"])]
        if hits:
            out = fetched_dir(p)
            out.mkdir(parents=True, exist_ok=True)
            for e in hits:
                blob = gh(f"repos/{owner}/{repo}/contents/{e['path']}?ref={ref}")
                (out / e["name"]).write_bytes(base64.b64decode(blob["content"]))
            what = ("the commit of its .cargo_vcs_info.json" if ref == sha
                    else f"the ref {ref} (the commit {sha} of its .cargo_vcs_info.json is not on "
                    "GitHub)")
            (out / "SOURCE").write_text(
                f"https://github.com/{owner}/{repo}/tree/{ref}/{d}\n"
                f"{n} {v} publishes no license file; these are the files of its repository at "
                f"{what}.\n")
            return None
    return (f"no license file in github.com/{owner}/{repo} at {ref} ({sub or 'root'} and parents);"
            f" write licenses/fetched/{n}-{v}/NOTE by hand")


def copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def vkd3d():
    tmp = os.environ.get("TMPDIR", "/tmp").rstrip("/")
    tarball = Path(os.environ.get("MDS_VKD3D_OUT", f"{tmp}/mds-vkd3d")) / "dl/vkd3d-2.1.tar.xz"
    build = (REPO / "tools/vkd3d/build.sh").read_text()
    url = re.search(r"^VKD3D_URL=(\S+)", build, re.M).group(1)
    sha = re.search(r"^VKD3D_SHA=(\S+)", build, re.M).group(1)
    if not tarball.is_file():
        die(f"{tarball} missing; run tools/vkd3d/build.sh")
    if hashlib.sha256(tarball.read_bytes()).hexdigest() != sha:
        die(f"{tarball} is not the tarball of tools/vkd3d/build.sh")
    out = OUT / "vkd3d"
    with tarfile.open(tarball) as t:
        for name in ["LICENSE", "COPYING", "AUTHORS"]:
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(t.extractfile(f"vkd3d-2.1/{name}").read())
    patches = sorted((REPO / "tools/vkd3d/patches").glob("*.patch"))
    for f in patches:
        copy(f, out / "patches" / f.name)
    (out / "SOURCE.md").write_text(
        "# vkd3d-shader source\n\n"
        "The vkd3d-shader library in this package (libvkd3d-shader.1.dylib, libvkd3d-shader.so.1, "
        "or libvkd3d-shader-1.dll) is built by `tools/vkd3d/build.sh` of MikuDanceStudio-J from "
        "the vkd3d 2.1 release with the patches in `patches/` applied:\n\n"
        f"- source: {url}\n"
        f"- sha256: {sha}\n"
        + "".join(f"- patch: `patches/{f.name}`\n" for f in patches)
        + "\nThe build script and the patches are also in the MikuDanceStudio-J repository, "
        "<https://github.com/geekjapan/MikuDanceStudio-J>, under `tools/vkd3d/`.\n")


def crtmath():
    readme = (REPO / "rust/crates/mds-crtmath/README.md").read_text()
    m = re.search(r"## License\n.*?```\n(.*?)```", readme, re.S)
    if not m:
        die("no AOCL-LibM notice in rust/crates/mds-crtmath/README.md")
    out = OUT / "mds-crtmath/AOCL-LibM.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("rust/crates/mds-crtmath contains constants, tables, and algorithms translated "
                   "from AMD AOCL-LibM 5.3.2, which is under this notice "
                   "(rust/crates/mds-crtmath/README.md):\n\n" + m.group(1))


def rust_std():
    sysroot = subprocess.run(["rustc", "--print", "sysroot"], cwd=REPO / "rust", check=True,
                             capture_output=True, text=True).stdout.strip()
    doc = Path(sysroot) / "share/doc/rust"
    if not (doc / "COPYRIGHT-library.html").is_file():
        die(f"{doc}/COPYRIGHT-library.html missing")
    copy(doc / "COPYRIGHT-library.html", OUT / "rust/COPYRIGHT-library.html")
    for f in sorted((doc / "licenses").iterdir()):
        copy(f, OUT / "rust/licenses" / f.name)


def main():
    do_fetch = sys.argv[1:] == ["--fetch"]
    if sys.argv[1:] not in ([], ["--fetch"]):
        die("usage: licenses.py [--fetch]")
    crates = graph()
    texts = {}  # sha256 -> (bytes, [crate file names])
    rows, missing = [], []
    for p in crates:
        files, origin = package_files(p), "package"
        if not files:
            err = fetch(p) if do_fetch and not fetched_files(p) else None
            files, origin = fetched_files(p), "fetched"
            if any(r == "NOTE" for r, _ in files):
                origin = "note"
        if not files:
            missing.append(f"{p['name']} {p['version']}: {err or 'no license text'}")
            continue
        for rel, data in files:
            h = hashlib.sha256(data).hexdigest()
            texts.setdefault(h, (data, []))[1].append(f"{p['name']} {p['version']} ({rel})")
        rows.append([p["name"], p["version"], p.get("license") or "", p.get("repository") or "",
                     origin, " ".join(r for r, _ in files)])
    if missing:
        die("crates without a license text (run licenses.py --fetch):\n  " + "\n  ".join(missing))

    for g in GENERATED:
        t = OUT / g
        shutil.rmtree(t) if t.is_dir() else t.unlink(missing_ok=True)
    for src, dst in [("LICENSE", "LICENSE"), ("LICENSE-MIT", "LICENSE-MIT"),
                     ("docs/FORK.md", "FORK.md"),
                     ("recipes/bullet275/LICENSE.txt", "bullet-2.75/LICENSE.txt")]:
        copy(REPO / src, OUT / dst)
    vkd3d()
    crtmath()
    rust_std()
    if not (OUT / "mingw-runtime").is_dir():
        die("licenses/mingw-runtime missing; run tools/package/mingw-copyright.sh")
    with open(OUT / "crates.tsv", "w") as f:
        f.write("name\tversion\tlicense\trepository\ttext from\tfiles\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    with open(OUT / "THIRD-PARTY.txt", "wb") as f:
        f.write(f"License texts of the {len(rows)} third-party crates mds-app is built from "
                "(crates.tsv). Each text is given once, after the crates and files it comes "
                "from.\n".encode())
        for data, users in sorted(texts.values(), key=lambda t: t[1][0]):
            f.write(b"\n" + b"=" * 78 + b"\n")
            f.write("".join(f"{u}\n" for u in users).encode())
            f.write(b"-" * 78 + b"\n" + data.rstrip(b"\n") + b"\n")
    (OUT / "README.md").write_text(
        "# Licenses\n\n"
        "Written by `tools/package/licenses.py`; every package carries this folder.\n\n"
        "| Path | What |\n|---|---|\n"
        "| `LICENSE`, `LICENSE-MIT`, `FORK.md` | The repository's files, unchanged. `FORK.md` "
        "says which paths are MIT and which are license pending. |\n"
        "| `bullet-2.75/` | Bullet 2.75 (`recipes/bullet275`), linked into mds-app through "
        "mds-bullet-sys. |\n"
        "| `vkd3d/` | vkd3d-shader 2.1, the library beside mds-app: its LICENSE, COPYING, "
        "AUTHORS, the applied patches, and where its source is (`SOURCE.md`). |\n"
        "| `mingw-runtime/` | Windows package: the MinGW-w64 runtime DLLs beside the vkd3d-shader "
        "DLL (`mingw-copyright.sh`). |\n"
        "| `mds-crtmath/` | The AOCL-LibM notice of rust/crates/mds-crtmath. |\n"
        "| `rust/` | The Rust standard library of the pinned toolchain, linked into mds-app. |\n"
        f"| `crates.tsv`, `THIRD-PARTY.txt` | The {len(rows)} third-party crates and their "
        "license texts. |\n"
        "| `fetched/` | Texts of crates that publish none, from their repositories. |\n")
    print(f"licenses.py: {len(rows)} crates, {len(texts)} distinct texts, "
          f"{sum(r[4] == 'fetched' for r in rows)} from repositories")


main()
