#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#define ARRAY_SIZE(x) (sizeof(x) / sizeof(*(x)))
struct vkd3d_spirv_stream { unsigned int word; };
struct vkd3d_spirv_builder { struct vkd3d_spirv_stream debug_stream; };
typedef enum SpvOp { SpvOpMemberName = 6 } SpvOp;
#ifdef WRONG_ENUM_OWNER
typedef enum OtherOp { OtherMemberName = 6 } OtherOp;
#define SpvOpMemberName OtherMemberName
#endif
#ifdef WRONG_RECORD_OWNER
struct other_spirv_builder { struct vkd3d_spirv_stream debug_stream; };
#define vkd3d_spirv_builder other_spirv_builder
#endif
#if defined(SAME_NAME_SHADOW) || defined(FUNCTION_POINTER)
extern int shadow_vsnprintf(char *, size_t, const char *, va_list);
#endif
#ifdef SAME_NAME_SHADOW
#define vsnprintf shadow_vsnprintf
#endif
#ifdef ASM_IDENTITY
extern int named_vsnprintf(char *, size_t, const char *, va_list) __asm__("vsnprintf");
#define vsnprintf named_vsnprintf
#endif
#ifdef WRONG_SIGNATURE
#define TARGET_ID int
#else
#define TARGET_ID uint32_t
#endif
extern unsigned int vkd3d_spirv_string_word_count(const char *name);
extern unsigned int vkd3d_spirv_opcode_word(SpvOp opcode, unsigned int count);
extern void vkd3d_spirv_build_word(struct vkd3d_spirv_stream *stream, unsigned int word);
extern void vkd3d_spirv_build_string(struct vkd3d_spirv_stream *stream, const char *name, unsigned int size);
extern void unknown_consumer(va_list args);
extern void unknown_non_cursor_call(void);
static void vkd3d_spirv_build_op_member_name(struct vkd3d_spirv_builder *builder,
        TARGET_ID type_id, uint32_t member, const char *fmt, ...)
{
    struct vkd3d_spirv_stream *stream = &builder->debug_stream;
    unsigned int name_size;
    char name[1024];
    va_list args;
#ifdef FUNCTION_POINTER
    int (*vsnprintf)(char *, size_t, const char *, va_list) = shadow_vsnprintf;
#endif

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
#ifdef FMT_REASSIGNMENT
    fmt = "%s";
#endif
#ifdef FMT_ESCAPE
    const char **alias = &fmt;
    (void)alias;
#endif
#ifdef UNKNOWN_NON_CURSOR_CALL
    unknown_non_cursor_call();
#endif
#ifdef UNKNOWN_BUILTIN
    __builtin_memcpy(name, args, 1);
#elif defined(UNKNOWN_CALL)
    unknown_consumer(args);
#else
    vsnprintf(name, ARRAY_SIZE(name), fmt, args);
#endif
#ifndef MISSING_TERMINATOR
    name[ARRAY_SIZE(name) - 1] = '\0';
#endif
#ifdef BRANCH
    if (name[0]) va_end(args);
#elif !defined(MISSING_END)
    va_end(args);
#endif

    name_size = vkd3d_spirv_string_word_count(name);
    vkd3d_spirv_build_word(stream, vkd3d_spirv_opcode_word(SpvOpMemberName, 3 + name_size));
    vkd3d_spirv_build_word(stream, type_id);
    vkd3d_spirv_build_word(stream, member);
    vkd3d_spirv_build_string(stream, name, name_size);
}
#ifdef GLOBAL_TAIL
unsigned int reg_idx;
#endif
void cursor_entry(struct vkd3d_spirv_builder *builder, uint32_t type_id, uint32_t member,
        unsigned int index)
{
#ifdef WRONG_TAIL
    int reg_idx = index;
#elif !defined(GLOBAL_TAIL)
    unsigned int reg_idx = index;
#endif
    vkd3d_spirv_build_op_member_name(builder, type_id, member, "cb%u", reg_idx);
#ifdef EXTRA_TARGET_CALL
    vkd3d_spirv_build_op_member_name(builder, type_id, member, "cb%u", reg_idx);
#endif
}

double cursor_scalar_identity(double value)
{
    return value;
}
