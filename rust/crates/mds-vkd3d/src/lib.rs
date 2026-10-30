// Copyright (C) 2001 Nikos Mavroyanopoulos
// Copyright (C) 2004 Hans Leidekker
// SPDX-License-Identifier: LGPL-2.1-or-later
//
// Modified on 2026-10-27 by translating the checksum implementation to Rust.
// Ported from vkd3d 2.1 libs/vkd3d-shader/checksum.c. This library is free
// software under LGPL version 2.1 or later, without any warranty. See LICENSE.
// The original MD5 implementation is based on Colin Plumb's public domain
// code from 1993. The algorithm is due to Ron Rivest.

//! The vkd3d-shader checksum core. MD5 is a format checksum, not a security hash.

#![forbid(unsafe_code)]

/// Selects the final-block padding used by vkd3d-shader.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Md5Variant {
    Standard,
    Dxbc,
}

/// Computes four little-endian digest words, matching vkd3d 2.1 on supported hosts.
///
/// Each returned word's `to_le_bytes()` gives the corresponding four digest bytes.
/// Like the native one-shot entry point, only the first `data.len() mod 2^32`
/// bytes are hashed. The native `size_t` argument narrows to `unsigned int`.
pub fn compute_md5(data: &[u8], variant: Md5Variant) -> [u32; 4] {
    let data = &data[..native_size(data.len())];
    let bit_count = (data.len() as u64) * 8;
    let mut state = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476];
    let mut blocks = data.chunks_exact(64);
    for block in &mut blocks {
        transform(&mut state, block);
    }

    let tail = blocks.remainder();
    let mut block = [0u8; 64];
    block[..tail.len()].copy_from_slice(tail);
    block[tail.len()] = 0x80;
    if tail.len() >= 56 {
        transform(&mut state, &block);
        block.fill(0);
    } else if variant == Md5Variant::Dxbc {
        block.copy_within(..tail.len() + 1, 4);
    }

    match variant {
        Md5Variant::Standard => block[56..].copy_from_slice(&bit_count.to_le_bytes()),
        Md5Variant::Dxbc => {
            let low_bits = bit_count as u32;
            block[..4].copy_from_slice(&low_bits.to_le_bytes());
            block[60..].copy_from_slice(&((low_bits >> 2) | 1).to_le_bytes());
        }
    }
    transform(&mut state, &block);
    state
}

fn native_size(size: usize) -> usize {
    size as u32 as usize
}

const CONSTANTS: [u32; 64] = [
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
];

const ROTATIONS: [u32; 64] = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9,
    14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15,
    21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

fn transform(state: &mut [u32; 4], block: &[u8]) {
    let mut words = [0u32; 16];
    for (word, bytes) in words.iter_mut().zip(block.chunks_exact(4)) {
        *word = u32::from_le_bytes(bytes.try_into().unwrap());
    }
    let [mut a, mut b, mut c, mut d] = *state;
    for i in 0..64 {
        let (f, index) = match i {
            0..16 => (d ^ (b & (c ^ d)), i),
            16..32 => (c ^ (d & (b ^ c)), (5 * i + 1) % 16),
            32..48 => (b ^ c ^ d, (3 * i + 5) % 16),
            _ => (c ^ (b | !d), (7 * i) % 16),
        };
        let next = a
            .wrapping_add(f)
            .wrapping_add(words[index])
            .wrapping_add(CONSTANTS[i])
            .rotate_left(ROTATIONS[i])
            .wrapping_add(b);
        a = d;
        d = c;
        c = b;
        b = next;
    }
    for (word, value) in state.iter_mut().zip([a, b, c, d]) {
        *word = word.wrapping_add(value);
    }
}

#[cfg(test)]
mod tests {
    use super::native_size;

    #[test]
    #[cfg(target_pointer_width = "64")]
    fn native_size_truncates_without_a_large_allocation() {
        for size in [
            0,
            1,
            u32::MAX as usize,
            1usize << 32,
            (1usize << 32) + 65,
            usize::MAX,
        ] {
            assert_eq!(native_size(size), size & 0xffff_ffff);
        }
    }
}
