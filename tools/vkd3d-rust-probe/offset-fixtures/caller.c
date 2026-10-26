#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
size_t offset_probe(unsigned int, long long);
size_t native_offset_probe(unsigned int, long long);
int main(void)
{
    const long long indices[] = {0, 1, 3, -1, -5, UINT32_MAX, INT64_MAX, 4611686018427387904LL};
    unsigned int count = 0;
    for (unsigned int which = 0; which < 25; ++which)
        for (unsigned int i = 0; i < sizeof(indices) / sizeof(indices[0]); ++i)
        {
            size_t actual = offset_probe(which, indices[i]);
            size_t expected = native_offset_probe(which, indices[i]);
            if (actual != expected)
                fprintf(stderr, "case %u index %lld got %zu expected %zu\n", which, indices[i], actual, expected);
            assert(actual == expected);
            ++count;
        }
    assert(offset_probe(10, -1) == 12);
    assert(offset_probe(10, -5) == SIZE_MAX - 3);
    assert(offset_probe(11, UINT32_MAX) == (size_t)17179869196ULL);
    assert(offset_probe(12, 4611686018427387904LL) == 16);
    assert(offset_probe(19, 0) == 4 && offset_probe(20, 0) == 4);
    printf("Variable offsetof C/Rust numeric comparisons %u; actual shader expressions 10\n", count);
    return 0;
}
