#include <assert.h>
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*PFN_vkd3d_log)(const char *format, va_list args);
va_list compiler_native_layout;
#if defined(__linux__) && defined(__x86_64__)
typedef __typeof__(compiler_native_layout[0]) NativeRecord;
_Static_assert(offsetof(NativeRecord, gp_offset) == 0, "gp_offset");
_Static_assert(offsetof(NativeRecord, fp_offset) == 4, "fp_offset");
_Static_assert(offsetof(NativeRecord, overflow_arg_area) == 8, "overflow_arg_area");
_Static_assert(offsetof(NativeRecord, reg_save_area) == 16, "reg_save_area");
#elif defined(__linux__) && defined(__aarch64__)
_Static_assert(offsetof(va_list, __stack) == 0, "__stack");
_Static_assert(offsetof(va_list, __gr_top) == 8, "__gr_top");
_Static_assert(offsetof(va_list, __vr_top) == 16, "__vr_top");
_Static_assert(offsetof(va_list, __gr_offs) == 24, "__gr_offs");
_Static_assert(offsetof(va_list, __vr_offs) == 28, "__vr_offs");
#endif
static const void *marker;
static const char *original;
static int wrong_copy;

void check_layout(size_t size, size_t align, size_t slot_size, size_t slot_align)
{
    printf("C va_list size=%zu align=%zu pointer=%zu long=%zu int=%zu double=%zu\n",
            sizeof(va_list), _Alignof(va_list), sizeof(void *), sizeof(long), sizeof(int), sizeof(double));
    assert(size == sizeof(va_list) && align == _Alignof(va_list));
    assert(slot_size == 8 && slot_align == 8);
    assert(sizeof(int) == 4 && sizeof(double) == 8 && sizeof(void *) == 8);
}

static void consume(const char *format, va_list args)
{
    va_list a, b;
    char expected[512], result[512], tiny[5];
    int length;
    assert(format == original);
    assert(!strcmp(format, "%d|%d|%u|%ld|%lld|%s|%p|%a|%.2f|%d|%d|%d|%.1f|%zu"));
    printf("original-format=%s\n", format);
    fflush(stdout);
    va_copy(a, args);
    va_copy(b, args);
    assert(va_arg(a, int) == -123456789);
    if (wrong_copy) { assert(va_arg(a, int) == -123456789); }
    else { assert(va_arg(b, int) == -123456789); }
    assert(va_arg(a, int) == -7);
    assert(va_arg(a, unsigned int) == 4000000001u);
    assert(va_arg(a, long) == -1234567L);
    assert(va_arg(a, long long) == -9000000000000001LL);
    assert(!strcmp(va_arg(a, const char *), "native-cursor"));
    assert(va_arg(a, const void *) == marker);
    double zero = va_arg(a, double);
    assert(zero == 0.0 && signbit(zero));
    assert(va_arg(a, double) == 3.25);
    assert(va_arg(a, int) == 9);
    assert(va_arg(a, int) == 10);
    assert(va_arg(a, int) == 11);
    assert(va_arg(a, double) == 12.5);
    assert(va_arg(a, size_t) == 12345);
    va_end(a);
    va_end(b);
    snprintf(expected, sizeof(expected), format, -123456789, -7, 4000000001u,
            -1234567L, -9000000000000001LL, "native-cursor", marker, -0.0,
            3.25, 9, 10, 11, 12.5, (size_t)12345);
    va_copy(a, args);
    length = vsnprintf(tiny, sizeof(tiny), format, a);
    va_end(a);
    assert(length == (int)strlen(expected));
    assert(!memcmp(tiny, expected, sizeof(tiny) - 1) && tiny[4] == 0);
    va_copy(a, args);
    assert(vsnprintf(result, sizeof(result), format, a) == length);
    va_end(a);
    assert(!strcmp(result, expected));
    FILE *file = tmpfile();
    assert(file);
    va_copy(a, args);
    assert(vfprintf(file, format, a) == length);
    va_end(a);
    rewind(file);
    memset(result, 0, sizeof(result));
    assert(fread(result, 1, sizeof(result), file) == (size_t)length);
    assert(!strcmp(result, expected));
    assert(!fclose(file));
    printf("result=%s\ntruncated=%s length=%d retry=PASS copies=PASS vfprintf=PASS\n", result, tiny, length);
}

PFN_vkd3d_log get_callback(int mode, const void *value, const char *format)
{
    marker = value;
    original = format;
    wrong_copy = mode;
    return consume;
}
