# Local validation outputs

`MikuMikuDance.def` is the tracked linker export definition.
GPU captures, raw model/texture bytes, generated images, probe logs and analysis
JSON in this directory are local evidence and are ignored by Git. Some captures
contain externally supplied resources; they are not repository test fixtures.
Keep conclusions, reproduction commands and acceptance limits in `docs/RHI_*.md`.
Reproduce captures with the source tools and legally available external fixtures.
Small generated test fixtures belong in `tests`, with their generator/source.
