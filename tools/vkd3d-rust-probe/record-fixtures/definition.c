#include "shared.h"
int record_format(selected_record *r, union shared_union *u, enum shared_enum e,
                  POINTER_CONST int *p, int PARAMETER_CONST n,
                  int (CALLBACK_ABI *callback)(CALLBACK_ARGUMENT_TYPE), ...) {
#if defined(EXPECTED_CHAR_SIGNED)
    if (r) return r->abi_callback((char)n);
#endif
    return r != 0 || u != 0 || e || p != 0 || n || callback != 0;
}
