#ifndef FIELD_TYPE
#define FIELD_TYPE int
#endif
#ifndef FIELD_NAME
#define FIELD_NAME value
#endif
#ifndef ARRAY_LENGTH
#define ARRAY_LENGTH 2
#endif
#ifndef ENUM_VALUE
#define ENUM_VALUE 1
#endif
#ifndef RECORD_ALIGNMENT
#define RECORD_ALIGNMENT 8
#endif
#ifndef UNION_ALIGNMENT
#define UNION_ALIGNMENT 8
#endif
#ifndef POINTER_CONST
#define POINTER_CONST const
#endif
#ifndef PARAMETER_CONST
#define PARAMETER_CONST const
#endif
#ifndef CALLBACK_ABI
#define CALLBACK_ABI
#endif
struct self;
typedef struct self self_alias;
struct mutual;
struct self { self_alias *next; struct mutual *peer; };
struct mutual { struct self *peer; };
#line 700 "presumed-not-physical.h"
#if defined(DIFFERENT_TAG)
struct other_record { int value; };
#elif defined(MACRO_DECL)
#define DECL struct shared_record { int value; };
DECL
#elif defined(FORWARD_ONLY)
struct shared_record;
#elif defined(UNION_KIND)
union shared_record { FIELD_TYPE FIELD_NAME; int array[ARRAY_LENGTH]; };
#else
#pragma pack(push, PACKING)
struct shared_record {
#if defined(REVERSE_FIELDS)
    int array[ARRAY_LENGTH]; FIELD_TYPE FIELD_NAME;
#else
    FIELD_TYPE FIELD_NAME; int array[ARRAY_LENGTH];
#endif
    self_alias *next;
    struct nested { int x; } nested;
} __attribute__((aligned(RECORD_ALIGNMENT)));
#pragma pack(pop)
#endif
union shared_union { char c; long n; } __attribute__((aligned(UNION_ALIGNMENT)));
enum shared_enum { first = ENUM_VALUE, second = 2 };
#if defined(DIFFERENT_TAG)
typedef struct other_record selected_record;
#elif defined(UNION_KIND)
typedef union shared_record selected_record;
#else
typedef struct shared_record selected_record;
#endif
#if !defined(BLOCK_SCOPE)
int record_format(
#if defined(PROTOTYPE_SCOPE)
                  struct prototype_record { int x; } *,
#else
                  selected_record *,
#endif
                  union shared_union *, enum shared_enum,
                  POINTER_CONST int *, int PARAMETER_CONST,
                  int (CALLBACK_ABI *callback)(int), ...);
#endif
