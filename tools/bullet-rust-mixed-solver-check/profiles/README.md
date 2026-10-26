# Exact arithmetic observation profiles

`macarm-appleclang21-rust1.95.json` records one measured native/Rust pair. It names exact compiler, target and macro output, producer source hashes, complete capture hashes and 1,948 specific raw-word disagreements in case 71, second scalar solve. All pairs are native `7fc00000` versus Rust `ffc00000` in fixed-slot velocity deltas after contact warmstart arithmetic.

The profile does not equate arbitrary NaNs. `observation.py` first requires exact event shapes and the entire enumerated inventory, then exact hashes for both full streams and all serialized inputs/final outputs. Any other native or Rust word, profile identity, count, location or producer source fails. Unit negative controls alter finite values, signed zero, infinity, an unrecorded NaN, a copied sign, discrepancy count/location and compiler identity. Every alteration must fail.

Raw full captures and the boundary experiment are retained with root evidence. Adding another profile requires examining its actual native/Rust capture and causal arithmetic boundary. The check has no record, update or accept-all switch. An unseen host difference remains a failed check until diagnosed.

The registration extension appends four scenarios without changing the original 96-scenario input/output/trace prefix or any of the 1,948 differences. `legacy_prefix` records the complete old input, original/native/Rust stdout and native/Rust trace hashes with exact line counts. The full capture hashes refer to the actual extended paired captures.

## Four-host measured captures

The four `*-run40411448747.json` profiles bind captures from source commit `bead7792eff1c9442cdbd3fa3aceaaf87fefe5ad`. macOS Apple clang 17 and Linux ARM clang 18 each have 1,948 ordered NaN-sign pairs. Linux x64 clang 18 has 696 pairs. Windows MSVC 19.44.35229 has 954 pairs. Each list contains exact native and Rust words, event, field and location. No finite, signed-zero, infinity, copied-field or ordering difference is accepted.

Every new profile includes raw metadata hashes and all six raw input, stdout and trace hashes. Windows input retains its measured CRLF bytes. The Windows identity also includes the actual compiler banner from `command-002.stderr`, retained by new runs as `compiler-banner.txt`. The old `compiler.txt` contains help output and cannot identify MSVC by itself.

The new profiles bind 217 producer files. This conservative set includes all Bullet headers, the compiled native translation units, shim headers, standalone runner and support modules, their Rust core modules, the complete CRT source directory, oracle and corpus generator. `sse_emu/emmintrin.h` is the actual checked-in emulation header. There is no checked-in `xmmintrin.h`. Existing captures recorded only 203 source entries. Replay verifies every recorded entry and reconstructs the complete producer set from the fixed Git commit, preserving Windows source CRLF bytes. Reconstruction does not claim those missing files were recorded by the original run. New live runs record the full set before any compiler command and check it before profile selection and in `finally` on success or failure. Verification scripts and profile JSON files also receive live integrity checks.

`replay_profiles.py` verifies the ZIP digest, old source manifest, reconstructed producer hashes, frozen fixtures, exact instrumented observer, full inventories, raw captures, schema, schedule and branch coverage. It streams trace members directly from the ZIP. Run it with `--artifacts-dir` and `--receipt`; optional `--hosts` resumes selected hosts without rereading completed captures. The receipt retains each completed host even if a later host fails.

These captures are observations, not four-host mutation receipts. New workflow execution must still run a clean compiled baseline, all 19 compiled semantic mutants and focused Clippy. Compiler, configuration and malformed-capture failures abort without reporting a caught mutant. The historical Apple clang 21 profile and its original producer hashes and legacy-prefix guards remain unchanged.
