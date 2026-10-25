# WAV fixtures for `mds-media`

Inputs and the oracle dump of the WAV loading code: `src/media/wave_audio.cpp`
(`LoadWaveFile`, `WaveLoadFile`, `WaveStartPlayback`, `WaveStreamRead`),
`src/media/wave_data_chunk.cpp` (`ScanWaveDataChunk`), and
`src/app/subsystem_init.cpp` (`WaveSeekAndFeed`).

| File | What it is | sha256 |
|---|---|---|
| `gen_wav.py` | Writes `wav/*.wav`. Deterministic (fixed LCG). | `ef9845b5bb078b5ba7b33cdda0a4c65ff1819851bc1fa7263e41911949aba363` |
| `wav/*.wav` | The 25 inputs; hashes in `SHA256SUMS`. | |
| `wave-dump.txt` | What the real C++ computes for them. | `240319fe79869e725298c616df08c2cba0d834a6ec2b78eba3e37eaa5d03be6b` |

## Regenerate

From the repository root, on a host with `clang++` and `python3`:

    python3 tests/fixtures/rust/media/gen_wav.py tests/fixtures/rust/media/wav
    tools/wave_check/run.sh tests/fixtures/rust/media/wav > tests/fixtures/rust/media/wave-dump.txt
    (cd tests/fixtures/rust/media/wav && shasum -a 256 *.wav) > tests/fixtures/rust/media/SHA256SUMS

`tools/wave_check/run.sh` compiles the real `wave_data_chunk.cpp`,
`wave_audio.cpp`, and `subsystem_init.cpp` against the shim headers in
`tools/wave_check/shim` (POSIX files stand in for Win32 files, GDI calls do
nothing, a fake `IDirectSound` records the buffer size) with AddressSanitizer.
Two runs give the same bytes.

`cargo test -p mds-media` (in `rust/`) loads the same files with the Rust code
and compares every field of the dump.

## Dump format

One block per file, sorted by name.

    file <name>
    scan ok <size> <offset> | scan fail     ScanWaveDataChunk from byte 36
    loaded 0|1                              LoadWaveFile accepted the file
    message <text>|none                     the message box text (English UI)

and, only when loaded:

    format <tag> <channels> <rate> <avg bytes/s> <block align> <bits> <cbSize>
    data <size> <offset>                    'data' chunk size and file offset
    buffer_bytes <ctx> <DirectSound>        nAvgBytesPerSec * 2, twice
    failures <n>                            short reads while building the waveform
    columns <n>
    max <n values>                          waveform max array
    min <n values>                          waveform min array
    seek <frame> <offset>                   WaveSeekAndFeed at frame / 30.0 s, for 8 frames

## What the inputs cover

| File | Case |
|---|---|
| `pcm8_mono_8000`, `pcm8_stereo_11025`, `pcm16_mono_11025`, `pcm16_stereo_22050`, `pcm16_stereo_44100` | PCM 8 and 16 bit, mono and stereo. The 22050 and 44100 Hz stereo files make columns that are not a whole number of bytes per second, so the skip path runs. |
| `pcm24_mono_8000` | 24 bit: accepted, read as 16 bit mono (the C++ picks the sample layout from the block align). |
| `odd_chunk_before_data`, `odd_data_size` | An odd-sized chunk with its pad byte before `data`; an odd `data` size. |
| `list_info_before_data`, `list_ddata_text` | A `LIST` chunk before `data`; a `LIST` text holding `ddata` (a mismatching byte is consumed, so this is not a match). |
| `list_decoy_data` | A `LIST` text holding a real `data` tag: the C++ takes it (size 64, offset 64). |
| `fmt_extended` | An 18-byte `fmt ` chunk. |
| `empty_data` | `data` size 0: one all-silence column. |
| `no_data_chunk`, `truncated_header`, `truncated_in_data_size`, `truncated_before_riff_end`, `data_size_negative` | Rejected: no `data`, cut inside the format fields, cut inside the size field, 3 bytes, size with the top bit set. |
| `truncated_data` | `data` claims 4000 bytes and the file holds 2000: accepted, the waveform stops at the short read. |
| `format_float`, `format_adpcm`, `not_riff`, `junk_before_fmt` | Rejected with the "not WAVE(PCM)" message: tag 3, tag 2, `RIFX`, a chunk ahead of `fmt ` (the tag is read at byte 20 whatever the chunks are). |
| `block_align_zero`, `rate_too_low` | Rejected silently: block align 0; a column of less than one block. |

The loader reads the format at fixed byte offsets and finds `data` by scanning
for the four letters. These fixtures pin that behavior, odd cases included.
