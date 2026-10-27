# Native va_list prerequisite experiment

This is a disposable ABI experiment. It does not integrate with the shader library, translator, Cargo workspace, or application. Four actual hosts and independent source review are required before drawing a portability conclusion.

Run from the repository root with Python 3, Clang, an archive tool, and Rust 1.95.0 installed.

```sh
python3 tools/vkd3d-valist-probe/run.py --out /tmp/native-valist-evidence --expect apple-arm64
```

The other accepted host names are `windows-x64`, `linux-x64`, and `linux-arm64`. The runner checks both the operating system architecture and the Rust host triple. Cross compilation and emulation do not satisfy this experiment.

## Boundary and alternatives

`include/vkd3d_types.h` in vkd3d 2.1 declares `typedef void (*PFN_vkd3d_log)(const char *format, va_list args);`. `vkd3d_shader_set_log_callback` exposes that callback publicly. The native export map uses `local: *` for private definitions. Private ellipsis definitions do not make the public callback optional.

The original `vkd3d_string_buffer_vprintf` makes a fresh `va_copy` before each `vsnprintf` retry. The consumer retains the original format and exercises the same copy-before-retry behavior.

The candidate stores arguments in a `repr(C)` union array with 8-byte stride and alignment. Pointers remain pointers; no integer round trip reconstructs them. Integers use their promoted C widths. Small signed integers become `int`, and `float` becomes `double`. The C test checks a platform-sized `long`, a 64-bit `long long`, and `size_t` separately.

The alternative of constructing register save areas requires separate GP and FP inventories, offsets, and alignment rules. This probe instead starts with exhausted register cursors and one overflow area. It does not implement that second alternative or assembly.

| Actual host | C va_list candidate | Initial exhausted state |
| --- | --- | --- |
| Windows x64 MSVC ABI | Pointer to 8-byte slots | Slot pointer |
| Apple ARM64 | Pointer to 8-byte slots | Slot pointer |
| Linux x64 SysV | Array-decayed record pointer | GP offset 48, FP offset 176, overflow pointer |
| Linux ARM64 AAPCS64 | Record by value | Stack pointer, GR and VR offsets zero |

C compiler record dumps, LLVM IR, runtime `sizeof`/alignment, and C member offset assertions independently check these candidate layouts. The LLVM IR also records the actual callback function-pointer ABI. Null register-area pointers are candidates only where the cursor offsets select the stack path. Acceptance on one architecture says nothing about the others.

The ABI references are the [Microsoft x64 calling convention](https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention), [Apple ARM64 platform ABI](https://developer.apple.com/documentation/xcode/writing-arm64-code-for-apple-platforms), [SysV x64 psABI](https://gitlab.com/x86-psABIs/x86-64-ABI/-/blob/master/x86-64-ABI/low-level-sys-info.tex), and [AAPCS64 variable argument rules](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst#appendix-support-for-variadic-routines).

## Checks and evidence

Rust obtains an actual `PFN_vkd3d_log` function pointer from C and calls it using the target candidate. C makes two independent `va_copy` objects and reads actual values through `va_arg`. One copy advances while the other must retain its first argument. Further fresh copies feed `vsnprintf` and `vfprintf` into a real temporary stream. A short first buffer must truncate, and a second fresh copy must reproduce the entire expected text.

Four deliberate corruptions must fail the actual C consumer comparisons. They change the initial slot, shift the cursor, place an unpromoted float representation in a double slot, and reuse an advanced copy. Each failed C condition emits `VALIST_REJECT field=<name>` and exits with code 86. Conditions evaluate once, including each `va_arg`. There are no platform assertion dialogs.

| Corruption | Required rejected field |
| --- | --- |
| `wrong-slot` | `first_int` |
| `wrong-offset` | `first_int` |
| `wrong-promotion` | `promoted_double` (3.25) |
| `wrong-copy` | `independent_copy` |

The runner requires exit 86 and exactly one rejection marker naming the intended field. Missing, duplicate, or different markers, crashes, other exits, and timeouts fail the run.

After a successful positive build, the runner compiles an intentionally invalid Rust configuration with JSON diagnostics. It requires exactly the three `E0308` errors at the `f32`, `i8`, and `u128` fixture expressions, with their expected promoted types. Unrelated compiler errors fail the run.

Every fixture argument expression is wrapped by one evaluation counter. The successful call must evaluate exactly 14 arguments, and the C consumer must read all 14 in order. This tests this fixture's packing only. It does not prove future generator lowering.

Only the listed union representations are accepted. Aggregates, vectors, `long double`, 128-bit integers, and unpromoted narrow arguments are unsupported. There is no arbitrary argument input or general printf parser. Unknown runtime modes and unsupported targets fail explicitly. A later generator must reject types outside its proven promoted inventory.

`receipt.json` records exact command arrays, exits, host, source hashes before and in `finally`, and SHA256 for sources, binary, archive, IR, and raw logs. A timeout records a null exit, `timed_out`, the deadline in seconds, and partial output before the exception propagates. Stderr is redirected into stdout; any separately captured stderr is also retained. The four-host workflow uploads that evidence even after a failure. The evidence directory must be outside this source directory.

Run `python3 tools/vkd3d-valist-probe/test_negative_gates.py` for cheap Python controls that reject false acceptance without launching a compiler or native process. The native runner retains raw diagnostics for independent inspection. A compiler failure, timeout, queued job, or workflow file is not a successful ABI test. Neither C nor the prototype belongs in the product.
