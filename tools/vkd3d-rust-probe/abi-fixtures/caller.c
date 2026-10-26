#include <assert.h>
#include <stdio.h>
#define COMCALL __attribute__((ms_abi))
typedef double (COMCALL *mixed_fn)(long, double, long, double, long, double, long, double);
typedef double (COMCALL *legacy_fn)();
struct abi_vtable { mixed_fn mixed; legacy_fn legacy; };
extern double COMCALL translated_mixed(long, double, long, double, long, double, long, double);
extern struct abi_vtable *translated_table(void);
extern long translated_c(long, long);
extern double translated_call_native(void);
extern long COMCALL translated_legacy(void);
extern double translated_call_native_mixed(void);
extern double translated_call_native_legacy(void);
double COMCALL native_callback(long a, double b, long c, double d,
        long e, double f, long g, double h)
{
    return 8*a + 7*b + 6*c + 5*d + 4*e + 3*f + 2*g + h;
}
static struct abi_vtable native_vtable = {native_callback, native_callback};
struct abi_vtable *native_table(void) { return &native_vtable; }
int main(void)
{
    assert(translated_mixed(1, 2.0, 3, 4.0, 5, 6.0, 7, 8.0) == 204.0);
    assert(translated_table()->mixed(1, 2.0, 3, 4.0, 5, 6.0, 7, 8.0) == 204.0);
    assert(translated_table()->legacy(1, 2.0, 3, 4.0, 5, 6.0, 7, 8.0) == 204.0);
    assert(translated_legacy() == 17);
    assert(translated_c(7, 9) == 86);
    assert(translated_call_native() == 120.0);
    assert(translated_call_native_mixed() == 120.0);
    assert(translated_call_native_legacy() == 120.0);
    puts("C to Rust Win64 direct/vtable 204; Rust to C Win64 direct/vtable/NoProto 120; C ABI 86");
    return 0;
}
