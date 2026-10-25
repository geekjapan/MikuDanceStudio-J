//! WAV loading with the timeline waveform, and an AVI writer for recording.
//!
//! [`wav`] ports the loading side of `src/media/wave_audio.cpp`
//! (`WaveLoadFile`, `WaveStreamRead`, and the seek arithmetic of
//! `WaveSeekAndFeed` in `src/app/subsystem_init.cpp`) and
//! `src/media/wave_data_chunk.cpp` (`ScanWaveDataChunk`). DirectSound
//! playback is left out; [`wav::Wave`] exposes the PCM bytes, the format and
//! the byte offset a player seeks to. `tests/wav_dump.rs` compares the
//! results with the dump of `tools/wave_check`, which runs the real C++.
//!
//! [`avi`] has no C++ twin (the C++ records through DirectShow). It writes
//! AVI 1.0 files by the format specification; `tests/avi_ffmpeg.rs` checks
//! them with `ffprobe` and `ffmpeg`.

pub mod avi;
pub mod wav;
