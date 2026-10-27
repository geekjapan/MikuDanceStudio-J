#include "fixture.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static void native_consumer(const char *format, va_list args)
{
    va_list a, b;
    va_copy(a, args);
    va_copy(b, args);
    if (strcmp(format, "%d %u %ld %lu %lld %llu %s %p %.1f %.2f %d %d %d %d")) abort();
    if (va_arg(a, int) != -123 || va_arg(a, unsigned) != 456) abort();
    if (va_arg(b, int) != -123 || va_arg(b, unsigned) != 456) abort();
    if (va_arg(a, long) != -789 || va_arg(a, unsigned long) != (unsigned long)(890ULL + (sizeof(unsigned long) == 8 ? 0x100000000ULL : 0))) abort();
    if (va_arg(a, long long) != -901 || va_arg(a, unsigned long long) != 1234ULL + 0x100000000ULL) abort();
    if (strcmp(va_arg(a, const char *), "text")) abort();
    int *marker = va_arg(a, void *);
    if (!marker || *marker != 91) abort();
    double negative_zero = va_arg(a, double);
    if (negative_zero != 0 || !signbit(negative_zero)) abort();
    if (va_arg(a, double) != 3.25) abort();
    if (va_arg(a, int) != 250 || va_arg(a, int) != 65530) abort();
    if (va_arg(a, int) != 65535 || va_arg(a, int) != 99) abort();
    va_end(a);
    va_end(b);
}

fixture_callback native_callback(void)
{
    return native_consumer;
}

int main(void)
{
    if (fixture_entry()) abort();
    puts("native two-TU variadic fixture PASS");
    return 0;
}
