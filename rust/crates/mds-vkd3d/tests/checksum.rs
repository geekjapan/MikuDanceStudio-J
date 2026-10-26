// SPDX-License-Identifier: LGPL-2.1-or-later
use mds_vkd3d::{compute_md5, Md5Variant};

fn digest(data: &[u8], variant: Md5Variant) -> String {
    compute_md5(data, variant)
        .into_iter()
        .flat_map(u32::to_le_bytes)
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

#[test]
fn standard_md5_vectors() {
    for (input, expected) in [
        ("", "d41d8cd98f00b204e9800998ecf8427e"),
        ("a", "0cc175b9c0f1b6a831c399e269772661"),
        ("abc", "900150983cd24fb0d6963f7d28e17f72"),
        ("message digest", "f96b697d7cb7938d525a2f31aaf161d0"),
        (
            "abcdefghijklmnopqrstuvwxyz",
            "c3fcd3d76192e4007dfb496cca67e13b",
        ),
        (
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "d174ab98d277d9f5a5611c2c9f419d9f",
        ),
        (
            "12345678901234567890123456789012345678901234567890123456789012345678901234567890",
            "57edf4a22be3c955ac49da2e2107b67a",
        ),
    ] {
        assert_eq!(digest(input.as_bytes(), Md5Variant::Standard), expected);
    }
    assert_eq!(
        digest(&vec![b'a'; 1_000_000], Md5Variant::Standard),
        "7707d6ae4e027c70eea2a935c2296f21"
    );
}

#[test]
fn pinned_native_standard_and_dxbc_fixtures() {
    let fixtures = include_str!("../../../../tests/fixtures/vkd3d-rust-checksum/native.tsv");
    let mut count = 0;
    for line in fixtures.lines().filter(|line| !line.starts_with('#')) {
        let fields: Vec<_> = line.split('\t').collect();
        assert_eq!(fields.len(), 4);
        let mut state = u32::from_str_radix(fields[0], 16).unwrap();
        let size: usize = fields[1].parse().unwrap();
        let data: Vec<_> = (0..size)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 17;
                state ^= state << 5;
                state as u8
            })
            .collect();
        for (variant, expected) in [
            (Md5Variant::Standard, fields[2]),
            (Md5Variant::Dxbc, fields[3]),
        ] {
            assert_eq!(
                digest(&data, variant),
                expected,
                "seed {} size {size} variant {variant:?}",
                fields[0]
            );
        }
        count += 1;
    }
    assert_eq!(count, 400);
}
