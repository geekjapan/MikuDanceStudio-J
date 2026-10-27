#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>

enum fixture_unsigned { FIXTURE_ENUM_NEGATIVE = -1, FIXTURE_ENUM = 65535 };
int private_format(const char *format, ...);
int private_zero(int value, ...);
int fixture_entry(void);
typedef void (*fixture_callback)(const char *format, va_list args);
fixture_callback native_callback(void);
