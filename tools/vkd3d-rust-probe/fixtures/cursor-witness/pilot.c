#include <stdarg.h>
#include <stdio.h>
extern void unknown_consumer(va_list args);
static void cursor_pilot(char *out, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
#ifdef ESCAPE
    va_list *alias = &args;
    (void)alias;
#endif
#ifdef ASSIGNMENT
    va_list other;
    args[0] = other[0];
#endif
#ifdef COPY
    va_list other;
    va_copy(other, args);
    va_end(other);
#endif
#ifdef UNKNOWN_BUILTIN
    __builtin_memcpy(out, args, 1);
#elif defined(UNKNOWN_CALL)
    unknown_consumer(args);
#else
    vsnprintf(out, 64, fmt, args);
#endif
#ifdef BRANCH
    if (out) va_end(args);
#elif !defined(MISSING_END)
    va_end(args);
#endif
}
void cursor_entry(char *out, unsigned int value)
{
    cursor_pilot(out, "cb%u", value);
}
