use std::fmt;
use std::path::PathBuf;

/// An error that names the original source file and line.
///
/// `line` is 1-based; 0 means the error has no line (for example an unreadable file).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FxError {
    pub path: PathBuf,
    pub line: u32,
    pub message: String,
}

impl FxError {
    pub fn new(path: impl Into<PathBuf>, line: u32, message: impl Into<String>) -> Self {
        FxError { path: path.into(), line, message: message.into() }
    }
}

impl fmt::Display for FxError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.line > 0 {
            write!(f, "{}:{}: {}", self.path.display(), self.line, self.message)
        } else {
            write!(f, "{}: {}", self.path.display(), self.message)
        }
    }
}

impl std::error::Error for FxError {}
