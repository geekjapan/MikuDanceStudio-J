//! Float math functions that reproduce the MSVC x64 UCRT bit for bit on its
//! FMA3 code paths (the ones modern x64 CPUs take), on any host.
//!
//! The functions are pure Rust: f32/f64 IEEE arithmetic plus `mul_add`,
//! which Rust defines as a single-rounding fused multiply-add on every
//! target. Results are the same on aarch64 and x86_64. NaN results are some
//! quiet NaN; the payload and sign are not those of the UCRT.
//!
//! Every function matches all 4096 block digests of
//! `tests/fixtures/rust/math/crt-digests-fma3.txt`; see README.md.

pub mod digest;
mod explog;
mod inv;
mod tables;
mod trig;

pub use explog::{expf, logf, powf};
pub use inv::{acosf, asinf, atan2f, atanf};
pub use trig::{cosf, sinf, tanf};

macro_rules! c_abi {
    ($($c:ident => $f:ident($($a:ident),+);)*) => {$(
        #[doc = concat!("C entry point for [`", stringify!($f), "`].")]
        #[no_mangle]
        pub extern "C" fn $c($($a: f32),+) -> f32 {
            $f($($a),+)
        }
    )*};
}

c_abi! {
    mds_crt_sinf => sinf(x);
    mds_crt_cosf => cosf(x);
    mds_crt_tanf => tanf(x);
    mds_crt_asinf => asinf(x);
    mds_crt_acosf => acosf(x);
    mds_crt_atanf => atanf(x);
    mds_crt_atan2f => atan2f(y, x);
    mds_crt_expf => expf(x);
    mds_crt_logf => logf(x);
    mds_crt_powf => powf(x, y);
}
