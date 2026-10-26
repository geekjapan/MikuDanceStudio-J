# Native shader contracts

`mds-shader corpus --manifest <file> <corpus-directory>` captures one row per
unique preprocessed effect and entry, using the existing compiler, scanner,
reflection probe, and SPIR-V coverage check. It requires complete discovery and
parsing. It needs no GPU. The production compiler backend is unchanged.

Each identity contains the file relative to the corpus root, profile, function,
compile arguments, and an FNV-1a 64-bit fingerprint of `Effect::shader_source()`.
The hash includes the expanded includes and is independent of compiler output and
checkout location. FNV-1a is a deterministic content fingerprint, not a security
checksum. Use the pinned corpus commit as the source provenance.

The versioned TSV starts with the format and compiler version, then a column
header. Cells percent-escape `%`, tab, CR, and LF. Each contract is `OK <value>`,
`ERR <diagnostic>`, or `UNAVAILABLE`. The final error column records rejected
compiles. Scan values include sorted input/output semantics and descriptors.
Reflection values include constant names, register classes, indices, and counts.
Reflection origin records CTAB or probe. Coverage and probe failures remain tied
to the same entry identity, including known gaps. No gap count is assumed to pass.

Capture and compare from the repository root:

```sh
(cd rust && MDS_VKD3D_LIB=/path/to/libvkd3d-shader.so.1 \
  cargo run --locked --release -p mds-shader -- \
  corpus --manifest ../candidate.tsv --emit ../shader-outputs /path/to/ray-mmd)
python3 tools/shader/compare.py --validate candidate.tsv
python3 tools/shader/compare.py tools/shader/native-baseline.tsv candidate.tsv
python3 -m unittest discover -s tools/shader -p 'test_*.py'
```

Capture can return 1 for existing reflection or coverage gaps. A complete
manifest still records those failures. A missing or malformed manifest fails
validation. Comparison preserves every successful native contract on the same
identity. Missing entries, changed sources, lost outputs, changed scans, and
changed reflection registers fail, even if aggregate success counts improve.
Existing failure diagnostics must remain identical or improve to success. A changed
failure or lost measurement fails. A final compile error can clear only when all
compile outputs succeed. Additional identities are allowed.
Generated backend text is retained through `--emit`; comparison protects backend
acceptance rather than byte-for-byte generated text.

The `Native shader contracts` workflow fetches the pinned ray-mmd corpus and
builds the pinned patched native vkd3d compiler. It always uploads the manifest,
summary, logs, provenance, and generated shader outputs as an artifact. Until a
verified native capture is checked in as `tools/shader/native-baseline.tsv`, it
captures a candidate and explicitly reports the missing frozen baseline.
Inspect the actual artifact and its provenance before freezing that manifest.
Workflow configuration alone is not native capture evidence. Baseline updates
must retain the reviewed native artifact rather than regenerate it from a
replacement compiler.
