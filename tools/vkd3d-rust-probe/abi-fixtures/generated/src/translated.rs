#![allow(
    clippy::missing_safety_doc,
    dead_code,
    non_camel_case_types,
    non_snake_case,
    non_upper_case_globals,
    unsafe_op_in_unsafe_fn,
    unused_assignments,
    unused_mut
)]
unsafe extern "C" {
    unsafe fn native_table() -> *mut abi_vtable;
}
pub type mixed_fn = Option<
    unsafe extern "win64" fn(
        ::core::ffi::c_long,
        ::core::ffi::c_double,
        ::core::ffi::c_long,
        ::core::ffi::c_double,
        ::core::ffi::c_long,
        ::core::ffi::c_double,
        ::core::ffi::c_long,
        ::core::ffi::c_double,
    ) -> ::core::ffi::c_double,
>;
pub type legacy_fn = Option<unsafe extern "win64" fn() -> ::core::ffi::c_double>;
#[derive(Copy, Clone)]
#[repr(C)]
pub struct abi_vtable {
    pub mixed: mixed_fn,
    pub legacy: legacy_fn,
}
unsafe extern "win64" {
    unsafe fn native_callback(
        _: ::core::ffi::c_long,
        _: ::core::ffi::c_double,
        _: ::core::ffi::c_long,
        _: ::core::ffi::c_double,
        _: ::core::ffi::c_long,
        _: ::core::ffi::c_double,
        _: ::core::ffi::c_long,
        _: ::core::ffi::c_double,
    ) -> ::core::ffi::c_double;
}
#[unsafe(no_mangle)]
pub unsafe extern "win64" fn translated_mixed(
    mut a: ::core::ffi::c_long,
    mut b: ::core::ffi::c_double,
    mut c: ::core::ffi::c_long,
    mut d: ::core::ffi::c_double,
    mut e: ::core::ffi::c_long,
    mut f: ::core::ffi::c_double,
    mut g: ::core::ffi::c_long,
    mut h: ::core::ffi::c_double,
) -> ::core::ffi::c_double {
    return a as ::core::ffi::c_double
        + 2 as ::core::ffi::c_int as ::core::ffi::c_double * b
        + (3 as ::core::ffi::c_long * c) as ::core::ffi::c_double
        + 4 as ::core::ffi::c_int as ::core::ffi::c_double * d
        + (5 as ::core::ffi::c_long * e) as ::core::ffi::c_double
        + 6 as ::core::ffi::c_int as ::core::ffi::c_double * f
        + (7 as ::core::ffi::c_long * g) as ::core::ffi::c_double
        + 8 as ::core::ffi::c_int as ::core::ffi::c_double * h;
}
#[unsafe(no_mangle)]
pub unsafe extern "win64" fn translated_legacy() -> ::core::ffi::c_long {
    return 17 as ::core::ffi::c_long;
}
static mut table: abi_vtable = unsafe {
    abi_vtable {
        mixed: Some(
            translated_mixed
                as unsafe extern "win64" fn(
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                ) -> ::core::ffi::c_double,
        ),
        legacy: ::core::mem::transmute::<
            Option<
                unsafe extern "win64" fn(
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                    ::core::ffi::c_long,
                    ::core::ffi::c_double,
                ) -> ::core::ffi::c_double,
            >,
            legacy_fn,
        >(
            Some(
                translated_mixed
                    as unsafe extern "win64" fn(
                        ::core::ffi::c_long,
                        ::core::ffi::c_double,
                        ::core::ffi::c_long,
                        ::core::ffi::c_double,
                        ::core::ffi::c_long,
                        ::core::ffi::c_double,
                        ::core::ffi::c_long,
                        ::core::ffi::c_double,
                    ) -> ::core::ffi::c_double,
            ),
        ),
    }
};
#[unsafe(no_mangle)]
pub unsafe extern "C" fn translated_table() -> *mut abi_vtable {
    return &raw mut table;
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn translated_c(
    mut a: ::core::ffi::c_long,
    mut b: ::core::ffi::c_long,
) -> ::core::ffi::c_long {
    return 11 as ::core::ffi::c_long * a + b;
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn translated_call_native() -> ::core::ffi::c_double {
    return native_callback(
        1 as ::core::ffi::c_long,
        2.0f64,
        3 as ::core::ffi::c_long,
        4.0f64,
        5 as ::core::ffi::c_long,
        6.0f64,
        7 as ::core::ffi::c_long,
        8.0f64,
    );
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn translated_call_native_mixed() -> ::core::ffi::c_double {
    return (*native_table())
        .mixed
        .expect(
            "non-null function pointer",
        )(
        1 as ::core::ffi::c_long,
        2.0f64,
        3 as ::core::ffi::c_long,
        4.0f64,
        5 as ::core::ffi::c_long,
        6.0f64,
        7 as ::core::ffi::c_long,
        8.0f64,
    );
}
#[unsafe(no_mangle)]
pub unsafe extern "C" fn translated_call_native_legacy() -> ::core::ffi::c_double {
    return ::core::mem::transmute::<
        _,
        unsafe extern "win64" fn(_, _, _, _, _, _, _, _) -> ::core::ffi::c_double,
    >(
        (*native_table()).legacy.expect("non-null function pointer"),
    )(
        1 as ::core::ffi::c_int,
        2.0f64,
        3 as ::core::ffi::c_int,
        4.0f64,
        5 as ::core::ffi::c_int,
        6.0f64,
        7 as ::core::ffi::c_int,
        8.0f64,
    );
}
