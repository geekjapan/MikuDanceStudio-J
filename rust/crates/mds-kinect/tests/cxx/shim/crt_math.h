// Force-included into the checked sources: their acosf is the MSVC x64 UCRT
// one of mds-crtmath. sqrtf and fabsf are exact everywhere.
#pragma once
#include <cmath>
extern "C" float mds_crt_acosf(float);
#define acosf mds_crt_acosf
