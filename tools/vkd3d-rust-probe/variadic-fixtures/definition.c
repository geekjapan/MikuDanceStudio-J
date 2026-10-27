#include "fixture.h"
#include <stdlib.h>
#include <string.h>

int private_zero(int value, ...)
{
    va_list args;
    va_start(args, value);
    va_end(args);
    return value;
}

int private_format(const char *format, ...)
{
    va_list args, copy;
    char tiny[5], full[256], bytes[256];
    va_start(args, format);
    va_copy(copy, args);
    native_callback()(format, copy);
    int result = 86;
    va_end(copy);
    va_copy(copy, args);
    int needed = vsnprintf(tiny, sizeof(tiny), format, copy);
    va_end(copy);
    va_copy(copy, args);
    int written = vsnprintf(full, sizeof(full), format, copy);
    va_end(copy);
    if (needed != written || needed < 5 || strncmp(tiny, full, 4)) abort();
    FILE *stream;
#ifdef _WIN32
    if (tmpfile_s(&stream)) abort();
#else
    stream = tmpfile();
#endif
    if (!stream) abort();
    va_copy(copy, args);
    if (vfprintf(stream, format, copy) != needed) abort();
    va_end(copy);
    rewind(stream);
    size_t count = fread(bytes, 1, sizeof(bytes), stream);
    if (fclose(stream) || count != (size_t)needed || memcmp(bytes, full, count)) abort();
    va_end(args);
    return result;
}
