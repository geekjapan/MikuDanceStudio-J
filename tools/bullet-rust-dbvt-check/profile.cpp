#include "observed-btDbvt.h"
#include <iostream>
#define STRING_VALUE_(x) #x
#define STRING_VALUE(x) STRING_VALUE_(x)
int main() {
#define RECORD(name) std::cout << #name "=" << STRING_VALUE(name) << '\n'
#define OBSERVED(name) std::cout << #name "=" << observed_##name << '\n'
    OBSERVED(DBVT_SELECT_IMPL);
    OBSERVED(DBVT_MERGE_IMPL);
    OBSERVED(DBVT_INT0_IMPL);
    OBSERVED(DBVT_USE_TEMPLATE);
    OBSERVED(DBVT_USE_INTRINSIC_SSE);
#ifdef WIN32
    std::cout << "WIN32=1\n";
#else
    std::cout << "WIN32=0\n";
#endif
#ifdef BT_USE_SSE
    std::cout << "BT_USE_SSE=1\n";
#else
    std::cout << "BT_USE_SSE=0\n";
#endif
#ifdef BT_HAS_ALIGNED_ALLOCATOR
    std::cout << "BT_HAS_ALIGNED_ALLOCATOR=1\n";
#else
    std::cout << "BT_HAS_ALIGNED_ALLOCATOR=0\n";
#endif
#ifdef BT_USE_DOUBLE_PRECISION
    std::cout << "BT_USE_DOUBLE_PRECISION=1\n";
#else
    std::cout << "BT_USE_DOUBLE_PRECISION=0\n";
#endif
#ifdef _MSC_VER
    RECORD(_MSC_VER);
#endif
#ifdef _WIN64
    RECORD(_WIN64);
#endif
}
