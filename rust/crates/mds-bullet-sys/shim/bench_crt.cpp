// Stand-ins for the mds_crt_* functions of mds-crtmath, for chain8_bench only:
// the double function rounded to float (the P1 det_math.h), not the UCRT.
#include <cmath>

extern "C" {
float mds_crt_sinf(float x) { return (float)std::sin((double)x); }
float mds_crt_cosf(float x) { return (float)std::cos((double)x); }
float mds_crt_tanf(float x) { return (float)std::tan((double)x); }
float mds_crt_asinf(float x) { return (float)std::asin((double)x); }
float mds_crt_acosf(float x) { return (float)std::acos((double)x); }
float mds_crt_atanf(float x) { return (float)std::atan((double)x); }
float mds_crt_atan2f(float y, float x) { return (float)std::atan2((double)y, (double)x); }
float mds_crt_expf(float x) { return (float)std::exp((double)x); }
float mds_crt_logf(float x) { return (float)std::log((double)x); }
float mds_crt_powf(float x, float y) { return (float)std::pow((double)x, (double)y); }
}
