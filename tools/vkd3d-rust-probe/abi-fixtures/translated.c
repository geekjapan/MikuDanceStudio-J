/* Test-only ABI fixture. No native helper enters the production compiler. */
#define COMCALL __attribute__((ms_abi))
typedef double (COMCALL *mixed_fn)(long, double, long, double, long, double, long, double);
typedef long (COMCALL *legacy_fn)();
struct abi_vtable { mixed_fn mixed; legacy_fn legacy; };
extern double COMCALL native_callback(long, double, long, double, long, double, long, double);
double COMCALL translated_mixed(long a, double b, long c, double d,
        long e, double f, long g, double h)
{
    return a + 2*b + 3*c + 4*d + 5*e + 6*f + 7*g + 8*h;
}
long COMCALL translated_legacy() { return 17; }
static struct abi_vtable table = {translated_mixed, translated_legacy};
struct abi_vtable *translated_table(void) { return &table; }
long translated_c(long a, long b) { return 11*a + b; }
double translated_call_native(void)
{
    return native_callback(1, 2.0, 3, 4.0, 5, 6.0, 7, 8.0);
}
