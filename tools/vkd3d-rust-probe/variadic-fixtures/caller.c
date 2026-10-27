#include "fixture.h"
#include <stdlib.h>

static int evaluations;
static int evaluated(int value) { ++evaluations; return value; }

static const char *evaluated_text(const char *value) { ++evaluations; return value; }
static void *evaluated_pointer(void *value) { ++evaluations; return value; }
static double evaluated_double(double value) { ++evaluations; return value; }

int fixture_entry(void)
{
    int marker = 91;
    unsigned char narrow_byte = 250;
    unsigned short narrow_short = 65530;
    enum fixture_unsigned enumeration = FIXTURE_ENUM;
    int result = private_format(evaluated_text("%d %u %ld %lu %lld %llu %s %p %.1f %.2f %d %d %d %d"),
        evaluated(private_zero(-123)), (unsigned)evaluated(456), (long)evaluated(-789),
        (unsigned long)(evaluated(890) + (sizeof(unsigned long) == 8 ? 0x100000000ULL : 0)),
        (long long)evaluated(-901),
        (unsigned long long)evaluated(1234) + 0x100000000ULL, evaluated_text("text"), evaluated_pointer(&marker),
        evaluated_double(-0.0), (float)evaluated_double(3.25),
        (unsigned char)evaluated(narrow_byte), (unsigned short)evaluated(narrow_short),
        (enum fixture_unsigned)evaluated(enumeration), evaluated(99));
    if (evaluations != 15 || result != 86) {
        fprintf(stderr, "evaluations=%d result=%d\n", evaluations, result);
        abort();
    }
    return 0;
}
