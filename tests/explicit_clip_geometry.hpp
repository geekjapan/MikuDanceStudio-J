#pragma once
#include <array>
#include <vector>
#include <algorithm>
#include <cmath>
#include <utility>
#include <limits>
// Diagnostic CPU clipping, not an emulation of any driver's clipping precision.
// Default: double intersections through all six planes, final float4 upload.
// Optional policies round only newly created intersections. Distances, edge
// evaluation, plane order and final nearest upload remain the same.
namespace explicit_clip_geometry {
using Vertex=std::array<float,4>;
using Double=std::array<double,4>;
enum class Rounding { Deferred, Nearest, Zero, Down, Up };
struct Policy {Rounding rounding=Rounding::Deferred;unsigned mask=15;};
struct Intersection {unsigned plane;Double before,after;};
inline double Round(double value,Rounding rounding) {
    if(rounding==Rounding::Deferred)return value;
    const float nearest=static_cast<float>(value);float out=nearest;
    const float inf=(std::numeric_limits<float>::infinity)();
    if((rounding==Rounding::Down && double(nearest)>value) ||
       (rounding==Rounding::Zero && value<0 && double(nearest)<value))
        out=std::nextafter(nearest,rounding==Rounding::Down?-inf:inf);
    if((rounding==Rounding::Up && double(nearest)<value) ||
       (rounding==Rounding::Zero && value>0 && double(nearest)>value))
        out=std::nextafter(nearest,rounding==Rounding::Up?inf:-inf);
    return out;
}
inline std::array<Double,6> Planes(unsigned width,unsigned height,unsigned guardPixels=0) {
    const double x=1-2.*guardPixels/width,y=1-2.*guardPixels/height;
    return {{{1,0,0,x},{-1,0,0,x},{0,1,0,y},{0,-1,0,y},{0,0,1,0},{0,0,-1,1}}};
}
inline std::array<Double,6> NearFarPlanes() {
    // Zero distances skip side planes without introducing a separate W plane.
    return {{{0,0,0,0},{0,0,0,0},{0,0,0,0},{0,0,0,0},{0,0,1,0},{0,0,-1,1}}};
}
inline double Distance(const Double& v,const Double& plane) {
    double sum=0;for(unsigned k=0;k<4;++k)sum+=v[k]*plane[k];return sum;
}
inline Double Intersect(const Double& a,const Double& b,double da,double db,Policy policy={},unsigned plane=0,std::vector<Intersection>* trace=nullptr) {
    const double t=da/(da-db);Double before,result;
    for(unsigned k=0;k<4;++k){before[k]=a[k]+(b[k]-a[k])*t;result[k]=policy.mask&(1u<<k)?Round(before[k],policy.rounding):before[k];}
    if(trace)trace->push_back({plane,before,result});return result;
}
inline std::vector<Vertex> Polygon(const std::vector<Vertex>& input,const std::array<Double,6>& planes,Policy policy={},std::vector<Intersection>* trace=nullptr) {
    std::vector<Double> polygon;for(const auto& v:input)polygon.push_back({v[0],v[1],v[2],v[3]});
    for(unsigned at=0;at<planes.size();++at){const auto& plane=planes[at];if(polygon.empty())break;std::vector<Double> next;Double previous=polygon.back();double dp=Distance(previous,plane);
        for(const auto& current:polygon){const double dc=Distance(current,plane);
            if((dp>=0)!=(dc>=0))next.push_back(Intersect(previous,current,dp,dc,policy,at,trace));
            if(dc>=0)next.push_back(current);previous=current;dp=dc;}polygon=std::move(next);}
    std::vector<Vertex> out;for(const auto& v:polygon)out.push_back({float(v[0]),float(v[1]),float(v[2]),float(v[3])});return out;
}
inline std::vector<Vertex> Line(const std::vector<Vertex>& input,const std::array<Double,6>& planes,Policy policy={},std::vector<Intersection>* trace=nullptr) {
    if(input.size()!=2)return {};Double a{input[0][0],input[0][1],input[0][2],input[0][3]},b{input[1][0],input[1][1],input[1][2],input[1][3]};
    for(unsigned at=0;at<planes.size();++at){const auto& plane=planes[at];const double da=Distance(a,plane),db=Distance(b,plane);if(da<0 && db<0)return {};
        if((da>=0)!=(db>=0)){const auto p=Intersect(a,b,da,db,policy,at,trace);if(da<0)a=p;else b=p;}}
    return {{float(a[0]),float(a[1]),float(a[2]),float(a[3])},{float(b[0]),float(b[1]),float(b[2]),float(b[3])}};
}
inline std::vector<Vertex> Fan(const std::vector<Vertex>& polygon,unsigned anchor=0) {
    if(polygon.size()<3 || anchor>=polygon.size())return {};std::vector<Vertex> out;
    for(unsigned n=1;n+1<polygon.size();++n){out.push_back(polygon[anchor]);out.push_back(polygon[(anchor+n)%polygon.size()]);out.push_back(polygon[(anchor+n+1)%polygon.size()]);}return out;
}
inline bool Visible(const std::vector<Vertex>& vertices,unsigned width,unsigned height,bool strict=false) {
    if(vertices.empty())return false;for(const auto& v:vertices){for(float f:v)if(!std::isfinite(f))return false;if(!(v[3]>0))return false;
        // Check both pre-center DX9 and corrected DX11 clip coordinates.
        for(unsigned corrected=0;corrected<2;++corrected){const double x=double(v[0])+(corrected?float(1.f/width)*v[3]:0),
                y=double(v[1])-(corrected?float(1.f/height)*v[3]:0),w=v[3];
            const double tolerance=strict?0:1e-6*w;
            if(x < -w-tolerance || x>w+tolerance || y < -w-tolerance || y>w+tolerance || v[2]<-tolerance || v[2]>w+tolerance)return false;
            if(strict && (x<=-w || x>=w || y<=-w || y>=w || v[2]<=0 || v[2]>=w))return false;
        }}return true;
}
}
