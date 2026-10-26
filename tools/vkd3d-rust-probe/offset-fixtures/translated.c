#include <stddef.h>
#include <stdint.h>

typedef struct { int a; float mod[3]; } use;
struct yield { int a; float mod[3]; };
typedef uint16_t row[3];
struct fixed { uint64_t head[2]; uint32_t data[4]; };
struct flexible { uint64_t head[2]; uint32_t data[]; };
struct packed { char head; uint32_t data[4]; } __attribute__((packed));
struct aligned { char head; uint32_t data[4]; } __attribute__((aligned(32)));
struct matrix { char head; row data[4]; };
struct element { uint64_t wide; char tail; };
struct elements { char head; struct element data[4]; };
typedef struct flexible flexible_alias;
static unsigned int counter;
static unsigned int next_index(void) { return counter++; }

size_t offset_probe(unsigned int which, long long index)
{
    counter = 3;
    switch (which)
    {
        case 10: return offsetof(struct fixed, data[index]);
        case 11: return offsetof(struct flexible, data[(uint32_t)index]);
        case 12: return offsetof(flexible_alias, data[(size_t)index]);
        case 13: return offsetof(struct packed, data[index]);
        case 14: return offsetof(struct aligned, data[index]);
        case 15: return offsetof(struct matrix, data[index]);
        case 16: return offsetof(struct elements, data[index]);
        case 17: { size_t result = offsetof(struct fixed, data[counter++]); return result + counter; }
        case 18: { size_t result = offsetof(struct fixed, data[next_index()]); return result + counter; }
        case 19: (void)offsetof(struct fixed, data[counter++]); return counter;
        case 20: (void)offsetof(struct fixed, data[next_index()]); return counter;
        case 21: return (unsigned char)offsetof(struct fixed, data[index]);
        case 22: return offsetof(struct fixed, data[(unsigned int)index * (unsigned int)8]);
        case 23: return offsetof(use, mod[(size_t)index]);
        case 24: return offsetof(struct yield, mod[(size_t)index]);
        ACTUAL_CASES
    }
    return 0;
}
