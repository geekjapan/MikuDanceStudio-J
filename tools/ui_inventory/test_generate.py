#!/usr/bin/env python3
"""Self-check of generate.py --check: stale rows fail, the rust column does not."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate as g  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    g.TSV, g.README = Path(tmp) / "inventory.tsv", Path(tmp) / "README.md"
    shutil.copy(g.HERE / "inventory.tsv", g.TSV)
    shutil.copy(g.HERE / "README.md", g.README)
    check = lambda: g.main(["generate.py", "--check"])  # noqa: E731
    assert check() == 0, "committed inventory is stale"

    lines = g.TSV.read_text(encoding="utf-8").split("\n")
    cells = lines[1].split("\t")
    cells[6] = "mds-ui::file::new"
    lines[1] = "\t".join(cells)
    g.TSV.write_text("\n".join(lines), encoding="utf-8")
    assert check() == 0, "a rust value must not make --check fail"

    cells[4] = "src/window/command_dispatch.cpp:1"
    lines[1] = "\t".join(cells)
    g.TSV.write_text("\n".join(lines), encoding="utf-8")
    assert check() == 1, "a changed handler must fail --check"

    g.main(["generate.py"])
    assert check() == 0 and "mds-ui::file::new" in g.TSV.read_text(encoding="utf-8"), \
        "regeneration must repair the row and keep the rust value"

    g.TSV.write_text("\n".join(lines[:-3]) + "\n", encoding="utf-8")
    assert check() == 1, "a dropped row must fail --check"
print("ok")
