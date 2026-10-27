int declared_first(int fixed, ...);
int declared_first(int fixed, ...) __asm__("effective_late_label");

int use_late_label(void)
{
    return declared_first(1, 2);
}
