# vkd3d checksum core in stable Rust

This crate ports the checksum algorithm from vkd3d 2.1 `libs/vkd3d-shader/checksum.c`.
It supports standard MD5 and the DXBC padding variant with no dependencies, native build, or unsafe code.
It is the first compiler-core unit. It does not compile shaders or replace the production `mds-shader` backend.

```rust
use mds_vkd3d::{compute_md5, Md5Variant};

let checksum = compute_md5(b"abc", Md5Variant::Dxbc);
let first_four_digest_bytes = checksum[0].to_le_bytes();
```

The result contains four little-endian digest words. This matches the native `uint32_t[4]` on all supported hosts.
The supported targets are Windows x64, Apple Silicon macOS, Linux x64, and Linux ARM64.
The native one-shot API narrows its `size_t` to a 32-bit unsigned byte count.
The Rust API preserves that behavior and hashes the first `data.len() mod 2^32` bytes.
MD5 is used only as a format checksum. It is unsuitable for cryptographic authentication.

Run the focused checks from `rust/`.

```sh
cargo fmt --check -p mds-vkd3d
cargo clippy --locked -p mds-vkd3d --all-targets -- -D warnings
cargo test --locked -p mds-vkd3d
```

The fixed fixtures cover both variants at every size from 0 through 129, additional block boundaries, and deterministic random multiblock inputs.
The native recapture tool also calls the original function with sizes of `2^32 + actual_size` and verifies the same digest without a large allocation.
See [the recapture instructions](../../../../tools/vkd3d-rust-checksum/README.md).

## Source and license

The checksum source credits Copyright (C) 2001 Nikos Mavroyanopoulos and Copyright (C) 2004 Hans Leidekker.
It describes its MD5 implementation as based on Colin Plumb's public domain code from 1993 and attributes the algorithm to Ron Rivest.
Those notices remain in `src/lib.rs`. This is a source translation licensed under LGPL-2.1-or-later.
[LICENSE](LICENSE) contains the full LGPL 2.1 text. [COPYING](COPYING) and [AUTHORS](AUTHORS) preserve the upstream project notices.
This classification does not establish acceptance of a product distribution or linking plan.
