#include "explicit_clip_geometry.hpp"
#include <cstdio>
using namespace explicit_clip_geometry;
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main() {
    const auto p=Planes(64,64);const std::vector<Vertex> line{{-2,0,.5f,1},{.5f,0,.5f,1}};
    const auto clipped=Line(line,p);CHECK(clipped.size()==2 && clipped[0][0]==-1 && clipped[1]==line[1]);
    CHECK(Line({{-2,0,.5f,1},{-3,0,.5f,1}},p).empty());
    const auto near=Line({{0,0,-1,1},{0,0,.5f,1}},p);CHECK(near.size()==2 && near[0][2]==0);
    const auto far=Line({{0,0,2,1},{0,0,.5f,1}},p);CHECK(far.size()==2 && far[0][2]==1);
    const std::vector<Vertex> outsideSides{{-10,0,.5f,1},{-20,0,.5f,1}};
    CHECK(Line(outsideSides,NearFarPlanes())==outsideSides && Line(outsideSides,p).empty());
    CHECK(Polygon({outsideSides[0],outsideSides[1],{0,10,.5f,1}},NearFarPlanes()).size()==3);
    CHECK(Line({{0,0,-1,1},{0,0,.5f,1}},NearFarPlanes())==near);
    const std::vector<Vertex> triangle{{-2,0,.5f,1},{0,1,.5f,1},{0,-1,.5f,1}};
    const auto poly=Polygon(triangle,p);CHECK(poly.size()==4);const auto fan=Fan(poly);CHECK(fan.size()==6 && Fan(poly,1).size()==6);
    // The clipped XY polygon has area 1.5; either fan must preserve that area.
    for(unsigned anchor=0;anchor<4;++anchor){const auto v=Fan(poly,anchor);double area=0;
        for(unsigned n=0;n<v.size();n+=3)area+=std::abs((v[n+1][0]-v[n][0])*(v[n+2][1]-v[n][1])-(v[n+2][0]-v[n][0])*(v[n+1][1]-v[n][1]))/2.;
        CHECK(area==1.5);}
    const auto interior=Polygon(triangle,Planes(64,64,2));CHECK(Visible(interior,64,64,true));
    const std::vector<Vertex> inside{{-.25f,-.25f,.5f,1},{.25f,-.25f,.5f,1},{0,.25f,.5f,1}};CHECK(Polygon(inside,p)==inside);
    CHECK(!Visible({{0,0,.5f,-1}},64,64));
    // Exact midpoint and directed negative rounding distinguish the policies.
    const double half=1+std::ldexp(1.,-24),next=1+std::ldexp(1.,-23);
    CHECK(Round(half,Rounding::Deferred)==half && Round(half,Rounding::Nearest)==1);
    CHECK(Round(half,Rounding::Zero)==1 && Round(half,Rounding::Down)==1 && Round(half,Rounding::Up)==next);
    CHECK(Round(-half,Rounding::Zero)==-1 && Round(-half,Rounding::Down)==-next && Round(-half,Rounding::Up)==-1);
    CHECK(Round(1,Rounding::Down)==1 && Round(-1,Rounding::Up)==-1);
    // Rounding generated Z never rounds untouched endpoint bytes or XYW.
    const std::vector<Vertex> sensitive{{-2,0,1,1},{0,0,1+std::ldexp(1.f,-23),1}};
    const auto unclampedPlanes=Planes(64,64);auto onlyX=unclampedPlanes;onlyX[5]={0,0,0,1};
    std::vector<Intersection> trace;const auto rounded=Line(sensitive,onlyX,{Rounding::Nearest,4},&trace);
    CHECK(rounded.size()==2 && rounded[1]==sensitive[1] && trace.size()==1);
    CHECK(trace[0].before[2]==half && trace[0].after[2]==1 && trace[0].before[0]==trace[0].after[0]);
    for(auto rule:{Rounding::Nearest,Rounding::Zero,Rounding::Down,Rounding::Up})CHECK(Polygon(inside,p,{rule,15})==inside);
    std::puts("explicit clipping/intersection rounding/ties/directions/untouched inputs passed");return 0;
}
