"""Compile the production PostModelReload body against the CPU oracle's app adapter."""
from pathlib import Path
import hashlib
import json
import sys

source_path = Path(sys.argv[1])
output = Path(sys.argv[2])
source_bytes = source_path.read_bytes()
source = source_path.read_text(encoding="utf-8")
helpers = source.split("mikudancestudio::mdl::BoneRecord* BoneAt(", 1)[1].split("} // namespace", 1)[0]
reload = source.split("void PostModelReload(MMDApp* app)", 1)[1].split("// (0x41A650", 1)[0]
assert helpers.count("void BonePoint(") == 1
assert "void PostModelReload2(" not in reload
output.write_text(
    "mikudancestudio::mdl::BoneRecord* BoneAt(" + helpers
    + "void PostModelReload(MMDApp* app)" + reload,
    encoding="utf-8",
)

snapshot = output.with_name("camera_reload_source.cpp")
snapshot.write_bytes(source_bytes)
manifest = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (snapshot, output)
}
output.with_name("camera_reload_manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
