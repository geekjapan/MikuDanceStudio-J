#pragma once
#include <math.h>
#ifdef __cplusplus
#include <cmath>
#endif
static inline float mds_sinf(float x) { return (float)sin((double)x); }
static inline float mds_cosf(float x) { return (float)cos((double)x); }
static inline float mds_tanf(float x) { return (float)tan((double)x); }
static inline float mds_asinf(float x) { return (float)asin((double)x); }
static inline float mds_acosf(float x) { return (float)acos((double)x); }
static inline float mds_atanf(float x) { return (float)atan((double)x); }
static inline float mds_atan2f(float y, float x) { return (float)atan2((double)y, (double)x); }
static inline float mds_expf(float x) { return (float)exp((double)x); }
static inline float mds_logf(float x) { return (float)log((double)x); }
static inline float mds_powf(float x, float y) { return (float)pow((double)x, (double)y); }
#define sinf mds_sinf
#define cosf mds_cosf
#define tanf mds_tanf
#define asinf mds_asinf
#define acosf mds_acosf
#define atanf mds_atanf
#define atan2f mds_atan2f
#define expf mds_expf
#define logf mds_logf
#define powf mds_powf
