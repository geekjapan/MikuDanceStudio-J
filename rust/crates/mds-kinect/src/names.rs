//! Shift-JIS names of the standard bones, with the trailing NUL the C++
//! compares (`memcmp(bone.name, k, sizeof k)`), so `"首"` does not match a
//! bone named `"首根"`. Same bytes as `kName*` in
//! `src/features/audio_pose_helpers.cpp` (the x86 constants).
//!
//! `src/app/oni_skeleton_pump.cpp` has `センテー` (0x65 instead of 0x5E) for
//! the center and `src/features/dialog_helpers.cpp` has seven bytes that decode
//! to `左殊` for the wrist, which no bone matches. This crate uses the
//! correct names.

pub const CENTER: &[u8] = b"\x83\x5A\x83\x93\x83\x5E\x81\x5B\0"; // センター
pub const UPPER_BODY: &[u8] = b"\x8F\xE3\x94\xBC\x90\x67\0"; // 上半身
pub const NECK: &[u8] = b"\x8E\xF1\0"; // 首
pub const LEFT_ARM: &[u8] = b"\x8D\xB6\x98\x72\0"; // 左腕
pub const RIGHT_ARM: &[u8] = b"\x89\x45\x98\x72\0"; // 右腕
pub const LEFT_ELBOW: &[u8] = b"\x8D\xB6\x82\xD0\x82\xB6\0"; // 左ひじ
pub const RIGHT_ELBOW: &[u8] = b"\x89\x45\x82\xD0\x82\xB6\0"; // 右ひじ
pub const LOWER_BODY: &[u8] = b"\x89\xBA\x94\xBC\x90\x67\0"; // 下半身
pub const LEFT_LEG: &[u8] = b"\x8D\xB6\x91\xAB\0"; // 左足
pub const RIGHT_LEG: &[u8] = b"\x89\x45\x91\xAB\0"; // 右足
pub const LEFT_LEG_IK: &[u8] = b"\x8D\xB6\x91\xAB\x82\x68\x82\x6A\0"; // 左足ＩＫ
pub const RIGHT_LEG_IK: &[u8] = b"\x89\x45\x91\xAB\x82\x68\x82\x6A\0"; // 右足ＩＫ
pub const LEFT_KNEE: &[u8] = b"\x8D\xB6\x82\xD0\x82\xB4\0"; // 左ひざ
pub const RIGHT_KNEE: &[u8] = b"\x89\x45\x82\xD0\x82\xB4\0"; // 右ひざ
pub const LEFT_WRIST: &[u8] = b"\x8D\xB6\x8E\xE8\x8E\xF1\0"; // 左手首
pub const RIGHT_WRIST: &[u8] = b"\x89\x45\x8E\xE8\x8E\xF1\0"; // 右手首
pub const LEFT_SHOULDER: &[u8] = b"\x8D\xB6\x8C\xA8\0"; // 左肩
pub const RIGHT_SHOULDER: &[u8] = b"\x89\x45\x8C\xA8\0"; // 右肩
pub const LEFT_ANKLE: &[u8] = b"\x8D\xB6\x91\xAB\x8E\xF1\0"; // 左足首

/// Whether a 20-byte PMD name field starts with `standard`.
pub fn matches(name: &[u8; 20], standard: &[u8]) -> bool {
    name[..standard.len()] == *standard
}

#[cfg(test)]
mod tests {
    use super::*;
    use encoding_rs::SHIFT_JIS;

    #[test]
    fn the_bytes_decode_to_the_names() {
        for (bytes, text) in [
            (CENTER, "センター"),
            (UPPER_BODY, "上半身"),
            (NECK, "首"),
            (LEFT_ARM, "左腕"),
            (RIGHT_ARM, "右腕"),
            (LEFT_ELBOW, "左ひじ"),
            (RIGHT_ELBOW, "右ひじ"),
            (LOWER_BODY, "下半身"),
            (LEFT_LEG, "左足"),
            (RIGHT_LEG, "右足"),
            (LEFT_LEG_IK, "左足ＩＫ"),
            (RIGHT_LEG_IK, "右足ＩＫ"),
            (LEFT_KNEE, "左ひざ"),
            (RIGHT_KNEE, "右ひざ"),
            (LEFT_WRIST, "左手首"),
            (RIGHT_WRIST, "右手首"),
            (LEFT_SHOULDER, "左肩"),
            (RIGHT_SHOULDER, "右肩"),
            (LEFT_ANKLE, "左足首"),
        ] {
            let (decoded, _, bad) = SHIFT_JIS.decode(&bytes[..bytes.len() - 1]);
            assert!(!bad && decoded == text, "{text}");
            assert_eq!(bytes.last(), Some(&0));
        }
    }

    #[test]
    fn the_terminator_is_part_of_the_match() {
        let mut name = [0u8; 20];
        name[..3].copy_from_slice(NECK);
        assert!(matches(&name, NECK));
        name[2] = 0x8E;
        assert!(!matches(&name, NECK));
    }
}
