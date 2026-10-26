"""Compile the production PostModelReload body against the CPU oracle's app adapter."""
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
helpers = source.split("mikudancestudio::mdl::BoneRecord* BoneAt(", 1)[1].split("} // namespace", 1)[0]
reload = source.split("void PostModelReload(MMDApp* app)", 1)[1].split("// (0x41A650", 1)[0]
assert helpers.count("void BonePoint(") == 1
assert "void PostModelReload2(" not in reload
Path(sys.argv[2]).write_text(
    "mikudancestudio::mdl::BoneRecord* BoneAt(" + helpers
    + "void PostModelReload(MMDApp* app)" + reload,
    encoding="utf-8",
)
