#include "unrelated.h"
#include "shared.h"
#if defined(BLOCK_SCOPE)
int record_caller(void) {
    struct block_record { int x; };
    extern int record_format(struct block_record *, union shared_union *, enum shared_enum,
                             const int *, int, int (*callback)(int), ...);
    return record_format(0, 0, first, 0, 0, 0);
}
#else
int record_caller(void) { return record_format(0, 0, first, 0, 0, 0); }
#endif
