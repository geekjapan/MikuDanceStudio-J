/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "vkd3d_shader_private.h"
#include <stdio.h>

int main(int argc, char **argv)
{
    unsigned char data[65536];
    uint32_t checksum[4], truncated[4];
    size_t size;
    FILE *input;

    _Static_assert(sizeof(size_t) == 8, "The oracle requires a supported 64-bit host");
    if (argc != 2 || !(input = fopen(argv[1], "rb")))
        return 2;
    size = fread(data, 1, sizeof(data), input);
    if (ferror(input) || !feof(input))
    {
        fclose(input);
        return 3;
    }
    fclose(input);
    for (int variant = VKD3D_MD5_STANDARD; variant <= VKD3D_MD5_DXBC; ++variant)
    {
        vkd3d_compute_md5(data, size, checksum, variant);
        /* The public size_t narrows before the source reads any input bytes. */
        vkd3d_compute_md5(data, (UINT64_C(1) << 32) + size, truncated, variant);
        if (memcmp(checksum, truncated, sizeof(checksum)))
            return 4;
        for (unsigned int i = 0; i < 4; ++i)
            for (unsigned int byte = 0; byte < 4; ++byte)
                printf("%02x", (checksum[i] >> (8 * byte)) & 0xff);
        printf(variant == VKD3D_MD5_STANDARD ? "\t" : "\n");
    }
    return 0;
}
