//! The failures of loading `Data\DxOpenNI.dll` and the texts the C++ shows
//! for them (`src/app/oni_kinect.cpp`, `OpenNiInit`). The UI picks `en` or
//! `jp` by the UI language and shows the message in a box titled
//! [`CAPTION`].

use std::fmt;

/// The caption of every message box of the loader.
pub const CAPTION: &str = "Kinect";

/// A text in both UI languages.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Message {
    pub en: &'static str,
    pub jp: &'static str,
}

const NOT_FOUND: Message = Message {
    en: "DxOpenNI.dll cannot find in Data folder.\n\nPlease download it from http://www.geocities.jp/higuchuu4/index_e.htm \nand set it into data folder.",
    jp: "DxOpenNI.dllがDataフォルダ内にありません。\n\nhttp://www.geocities.jp/higuchuu4/ よりDxOpenNI.dllをダウンロードして\nDataフォルダ内に置いて下さい。",
};
const CANNOT_MOVE: Message = Message {
    en: "Cannot move OpenNI.\nOpenNI might be failed install.",
    jp: "OpenNIが動作しません。おそらくOpenNIのインストールに失敗しています。\nOpenNIのサンプル、NiUserTrackerが正しく動作するようにOpenNIをインストールし直して下さい。",
};
const VERSION_130: Message = Message {
    en: "\"DxOpenNI.dll\" version is wrong.\n(Version1.30 is necessary)",
    jp: "DxOpenNI.dllのバージョンが異なります\n(バージョン1.30が必要です)",
};
const VERSION_RANGE: Message = Message {
    en: "\"DxOpenNI.dll\" version is wrong.\n(Version1.30 or 1.40 or 1.50 is necessary)",
    jp: "DxOpenNI.dllのバージョンが異なります\n(バージョン1.30～1.50までのどれか)",
};

/// Why [`crate::dll::OpenNi::start`] failed.
#[derive(Debug)]
pub enum Error {
    /// `Data\DxOpenNI.dll` is not there.
    NotFound,
    /// The DLL is there but does not load. `code` and `detail` are the
    /// Win32 error number and its text, which the C++ shows first in a box
    /// titled "error" ([`Error::win32_report`]).
    CannotLoad { code: u32, detail: String },
    /// One of the seven exports is missing: the DLL is not 1.30 or later.
    ExportMissing,
    /// `OpenNIGetVersion` returned something other than 1.30, 1.40 or 1.50.
    UnsupportedVersion,
    /// `OpenNIInit` returned false. The C++ shows no message.
    InitFailed,
}

impl Error {
    /// The message box of the failure, if the C++ shows one.
    pub fn message(&self) -> Option<Message> {
        match self {
            Error::NotFound => Some(NOT_FOUND),
            Error::CannotLoad { .. } => Some(CANNOT_MOVE),
            Error::ExportMissing => Some(VERSION_130),
            Error::UnsupportedVersion => Some(VERSION_RANGE),
            Error::InitFailed => None,
        }
    }

    /// The text of the extra "error" box shown before the message of
    /// [`Error::CannotLoad`] (`ShowWin32ErrorMessage`).
    pub fn win32_report(&self) -> Option<String> {
        match self {
            Error::CannotLoad { code, detail } => {
                Some(format!("GetProcAddress: {code}:{detail}\n"))
            }
            _ => None,
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.message() {
            Some(m) => f.write_str(m.en),
            None => f.write_str("OpenNIInit failed"),
        }
    }
}

impl std::error::Error for Error {}

#[cfg(test)]
mod tests {
    use super::*;
    use encoding_rs::SHIFT_JIS;

    /// The Shift-JIS bytes of the C++ `kJpOni*` arrays.
    const SJIS: [(&[u8], Message); 4] = [
        (b"\x44\x78\x4f\x70\x65\x6e\x4e\x49\x2e\x64\x6c\x6c\x82\xaa\x44\x61\x74\x61\x83\x74\x83\x48\x83\x8b\x83\x5f\x93\xe0\x82\xc9\x82\xa0\x82\xe8\x82\xdc\x82\xb9\x82\xf1\x81\x42\x0a\x0a\x68\x74\x74\x70\x3a\x2f\x2f\x77\x77\x77\x2e\x67\x65\x6f\x63\x69\x74\x69\x65\x73\x2e\x6a\x70\x2f\x68\x69\x67\x75\x63\x68\x75\x75\x34\x2f\x20\x82\xe6\x82\xe8\x44\x78\x4f\x70\x65\x6e\x4e\x49\x2e\x64\x6c\x6c\x82\xf0\x83\x5f\x83\x45\x83\x93\x83\x8d\x81\x5b\x83\x68\x82\xb5\x82\xc4\x0a\x44\x61\x74\x61\x83\x74\x83\x48\x83\x8b\x83\x5f\x93\xe0\x82\xc9\x92\x75\x82\xa2\x82\xc4\x89\xba\x82\xb3\x82\xa2\x81\x42", NOT_FOUND),
        (b"\x4f\x70\x65\x6e\x4e\x49\x82\xaa\x93\xae\x8d\xec\x82\xb5\x82\xdc\x82\xb9\x82\xf1\x81\x42\x82\xa8\x82\xbb\x82\xe7\x82\xad\x4f\x70\x65\x6e\x4e\x49\x82\xcc\x83\x43\x83\x93\x83\x58\x83\x67\x81\x5b\x83\x8b\x82\xc9\x8e\xb8\x94\x73\x82\xb5\x82\xc4\x82\xa2\x82\xdc\x82\xb7\x81\x42\x0a\x4f\x70\x65\x6e\x4e\x49\x82\xcc\x83\x54\x83\x93\x83\x76\x83\x8b\x81\x41\x4e\x69\x55\x73\x65\x72\x54\x72\x61\x63\x6b\x65\x72\x82\xaa\x90\xb3\x82\xb5\x82\xad\x93\xae\x8d\xec\x82\xb7\x82\xe9\x82\xe6\x82\xa4\x82\xc9\x4f\x70\x65\x6e\x4e\x49\x82\xf0\x83\x43\x83\x93\x83\x58\x83\x67\x81\x5b\x83\x8b\x82\xb5\x92\xbc\x82\xb5\x82\xc4\x89\xba\x82\xb3\x82\xa2\x81\x42", CANNOT_MOVE),
        (b"\x44\x78\x4f\x70\x65\x6e\x4e\x49\x2e\x64\x6c\x6c\x82\xcc\x83\x6f\x81\x5b\x83\x57\x83\x87\x83\x93\x82\xaa\x88\xd9\x82\xc8\x82\xe8\x82\xdc\x82\xb7\x0a\x28\x83\x6f\x81\x5b\x83\x57\x83\x87\x83\x93\x31\x2e\x33\x30\x82\xaa\x95\x4b\x97\x76\x82\xc5\x82\xb7\x29", VERSION_130),
        (b"\x44\x78\x4f\x70\x65\x6e\x4e\x49\x2e\x64\x6c\x6c\x82\xcc\x83\x6f\x81\x5b\x83\x57\x83\x87\x83\x93\x82\xaa\x88\xd9\x82\xc8\x82\xe8\x82\xdc\x82\xb7\x0a\x28\x83\x6f\x81\x5b\x83\x57\x83\x87\x83\x93\x31\x2e\x33\x30\x81\x60\x31\x2e\x35\x30\x82\xdc\x82\xc5\x82\xcc\x82\xc7\x82\xea\x82\xa9\x29", VERSION_RANGE),
    ];

    #[test]
    fn japanese_texts_are_the_cpp_bytes_decoded() {
        for (bytes, message) in SJIS {
            let (text, _, bad) = SHIFT_JIS.decode(bytes);
            assert!(!bad);
            assert_eq!(text, message.jp);
        }
    }

    #[test]
    fn each_failure_has_its_message() {
        assert_eq!(Error::NotFound.message(), Some(NOT_FOUND));
        assert_eq!(Error::ExportMissing.message(), Some(VERSION_130));
        assert_eq!(Error::UnsupportedVersion.message(), Some(VERSION_RANGE));
        assert!(Error::InitFailed.message().is_none());
        let e = Error::CannotLoad {
            code: 126,
            detail: "The specified module could not be found.".into(),
        };
        assert_eq!(e.message(), Some(CANNOT_MOVE));
        assert_eq!(
            e.win32_report().unwrap(),
            "GetProcAddress: 126:The specified module could not be found.\n"
        );
    }
}
