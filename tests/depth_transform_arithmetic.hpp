#pragma once
#include <array>
#include <cmath>

// Diagnostic hypotheses only. Volatile intermediates force the stated
// rounding boundaries on both x86 and x64; std::fma requests fused rounding.
namespace depth_diagnostic {
using Matrix = std::array<float,16>;
enum class Rounding { Sequential, Double, Paired, Fused };
inline float Dot(const float* a,const float* b,Rounding rounding) {
    if(rounding==Rounding::Double) {
        volatile double sum=0;
        for(unsigned k=0;k<4;++k){volatile double product=double(a[k])*b[k];sum=sum+product;}
        return static_cast<float>(sum);
    }
    if(rounding==Rounding::Fused) {
        float sum=0;for(unsigned k=0;k<4;++k)sum=std::fma(a[k],b[k],sum);return sum;
    }
    float products[4];for(unsigned k=0;k<4;++k){volatile float product=a[k]*b[k];products[k]=product;}
    if(rounding==Rounding::Paired) {
        volatile float left=products[0]+products[1],right=products[2]+products[3];
        volatile float sum=left+right;return sum;
    }
    volatile float sum=0;for(float product:products)sum=sum+product;return sum;
}
inline Matrix Multiply(const Matrix& a,const Matrix& b,Rounding rounding) {
    Matrix result{};
    for(unsigned row=0;row<4;++row)for(unsigned col=0;col<4;++col) {
        const float column[]={b[col],b[4+col],b[8+col],b[12+col]};
        result[row*4+col]=Dot(a.data()+row*4,column,rounding);
    }
    return result;
}
}
