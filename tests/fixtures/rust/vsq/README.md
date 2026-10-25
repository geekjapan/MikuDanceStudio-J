# VSQ lip sync fixtures

Input for `mds-vsq` and the dumps of the real C++ it must match. The C++ is
`LoadVsqFile` in `src/io/vsq_load.cpp`, the handler of menu 224 and of a
dropped `.vsq` file.

| Path | Content |
|---|---|
| `generate.py` | Writes every `*.vsq` and `cases.tsv`. Python 3 standard library only. |
| `*.vsq` | Generated Standard MIDI Files in the VOCALOID layout. |
| `cases.tsv` | One row per run: the file and the morph table of the model (`kModels` in `tools/vsq_check/vsq_check.cpp`). |
| `expected/<file>@<model>.txt` | The sibling `.txt` as the C++ leaves it. |
| `expected/<file>@<model>.<jp or en>.dump` | Outcome, message boxes, morph keys, frame. Format at the top of `tools/vsq_check/vsq_check.cpp`. |
| `SHA256SUMS` | Hashes of all of the above. |

## Regenerate and check

From the repository root, on macOS with clang++:

    python3 -I tests/fixtures/rust/vsq/generate.py
    tools/vsq_check/run.sh --update        # rewrites expected/ from the real C++
    (cd tests/fixtures/rust/vsq && shasum -a 256 generate.py cases.tsv *.vsq expected/* > SHA256SUMS)

Check without writing:

    tools/vsq_check/run.sh                 # builds the C++, diffs against expected/
    (cd tests/fixtures/rust/vsq && shasum -a 256 -c SHA256SUMS)
    cd rust && cargo test -p mds-vsq       # Rust against expected/

`run.sh` links the real `src/io/vsq_load.cpp` and the two read helpers of
`src/model/model_query_helpers.cpp` with the shim headers in
`tools/vsq_check/shim`. The shims stand in for Win32, the app object, and
`RegisterMorphKeyCurrent` (it records the morph index, the frame, and the
weight the file just stored). Build flags that matter: `-fshort-wchar` (the
file's path type is 2 bytes), `-ffp-contract=off` (MSVC x64 does not fuse),
`-ftrivial-auto-var-init=zero` (the file reads its `line` buffer before the
first `fgets` on some inputs).

## Cases

Every `.vsq` has a master track with the time signature, key signature and a
tempo, and one singer track, unless the row says otherwise. `full` is the
model with the four faces out of order and `あ` twice.

| File | What it pins | Outcome |
|---|---|---|
| `basic`, `vibrato`, `small-chunks`, `big-chunks`, `crlf`, `division-960`, `division-smpte`, `key-signatures` | One singer track; lyrics for every vowel; text split in 11, 119 and 247 byte meta events; CRLF text; other divisions; key signatures | ok |
| `vowels` | Every vowel, `M` as `u`, `m` and `N` as `n`, the synthesized `e`, an unknown vowel, a vowel `h` that takes the consonant, a consonant-only field, a one-letter lyric, `p\` with and without the space | ok on `full`; rejected on `no-a`, `no-i`, `no-u`, `no-o`, `no-a-no-o`, `lookalike` (names of two kana), `empty` (no morphs) |
| `consonants` | Every consonant class against each vowel | ok |
| `tempo-changes`, `tempo-on-note-tracks` | Five tempo changes (the walk reduces the tick by the next entry's absolute time); tempos in three tracks | ok |
| `one-track` | Tempo and text in the only track | ok |
| `multi-track` | Master and three singer tracks; only the first `[EventList]` is read | ok |
| `rests`, `overlap`, `long-notes` | Gaps, overlapping notes, notes of 100 seconds | ok |
| `empty-track`, `empty-track-first` | Tracks with only End of Track | ok |
| `no-notes` | `[EventList]` with the singer only: empty `.txt`, frame unchanged | ok |
| `long-line` | A 273 byte line, which `fgets` reads in two pieces; the second piece holds `Length=7` | ok |
| `bad-magic`, `bad-header-length`, `format-0-two-tracks` | The header is never checked | ok |
| `trunc-track`, `trunc-no-end-of-track`, `ntracks-too-many` | End of file reads as zeros | rejected: analysis error |
| `sysex`, `program-change`, `running-status`, `unknown-meta`, `sequence-number`, `short-text-event` | An event the walk has no case for | rejected (SysEx box for `sysex`) |
| `empty-file`, `empty-track-only`, `trunc-header`, `no-event-list`, `tempo-after-event-list` | A line the scans look for is not there | hang: the C++ loops forever (the harness stops after 1000 reads at end of file) |
| `header-only` | The file ends after the header | rejected |
| `one-note`, `bad-lyric-line` | One note makes the scan for the lyric land on a wrong line; a lyric line without `","` | fault: null write |
| `long-lyric`, `long-consonant` | A lyric of 8 bytes, a consonant of 6; `sprintf_s` ends the process | fault: sprintf_s overflow |

## What the dumps do not carry

- Windows opens the files in text mode: `\n` is written as `\r\n`, and `\r\n`
  is read as `\n`. The dumps are from macOS, so they hold `\n` only. A VSQ
  with CRLF text reaches the scans with a `\r` on Windows too (`crlf.vsq`
  has it in the data); the lip sync lines of the final file are CRLF.
- A lyric holding `%` is the format string of `sprintf_s` and has no defined
  result. No fixture has one.
- With notes and no tempo event the C++ reads `malloc(0)`. `mds-vsq` reports a
  fault; no fixture has this.
