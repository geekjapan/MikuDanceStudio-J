#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
size_t offset_probe(unsigned int, long long);
size_t native_offset_probe(unsigned int, long long);
size_t extracted_offset_probe(unsigned int, long long);
size_t layout_probe(unsigned int);
size_t native_layout_probe(unsigned int);
size_t extracted_layout_probe(unsigned int);
int main(void)
{
    for (unsigned int metric = 0; metric < LAYOUT_METRIC_COUNT; ++metric)
    {
        size_t expected = native_layout_probe(metric);
        assert(extracted_layout_probe(metric) == expected);
        assert(layout_probe(metric) == expected);
    }
    printf("Original/extracted/generated layout metrics %u\n", LAYOUT_METRIC_COUNT);
    const long long indices[] = {0, 1, 3, -1, -5, UINT32_MAX, INT64_MAX, 4611686018427387904LL};
    unsigned int count = 0;
    for (unsigned int which = 0; which < 25; ++which)
        for (unsigned int i = 0; i < sizeof(indices) / sizeof(indices[0]); ++i)
        {
            size_t actual = offset_probe(which, indices[i]);
            size_t expected = native_offset_probe(which, indices[i]);
            if (actual != expected)
                fprintf(stderr, "case %u index %lld got %zu expected %zu\n", which, indices[i], actual, expected);
            assert(extracted_offset_probe(which, indices[i]) == expected);
            assert(actual == expected);
            ++count;
        }
    /* The shader local is unsigned int even though the chunk's field is size_t. */
    assert(offset_probe(8, -1) == offset_probe(8, 0) + (size_t)UINT32_MAX * sizeof(uint32_t));
    assert(offset_probe(8, 4611686018427387904LL) == offset_probe(8, 0));
    assert(offset_probe(10, -1) == 12);
    assert(offset_probe(10, -5) == SIZE_MAX - 3);
    assert(offset_probe(11, UINT32_MAX) == (size_t)17179869196ULL);
    assert(offset_probe(12, 4611686018427387904LL) == 16);
    assert(offset_probe(19, 0) == 4 && offset_probe(20, 0) == 4);
    printf("Variable offsetof C/Rust numeric comparisons %u; actual shader expressions 10\n", count);
    return 0;
}
