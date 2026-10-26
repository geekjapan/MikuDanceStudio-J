#include "oracle-copy.cpp"
extern "C" int mds_consumer_oracle(int order) {
    char name[]="consumer-oracle";
    char rank[]={char('0'+order),0};
    char* argv[]={name,rank,nullptr};
    return consumer_oracle_main(2,argv);
}
extern "C" void mds_consumer_aabb(const uint32_t* words,uint32_t* result) {
    float values[12];
    std::memcpy(values,words,sizeof(values));
    const auto a=btDbvtVolume::FromMM(btVector3(values[0],values[1],values[2]),btVector3(values[3],values[4],values[5]));
    const auto b=btDbvtVolume::FromMM(btVector3(values[6],values[7],values[8]),btVector3(values[9],values[10],values[11]));
    result[0]=Intersect(a,b);
    btDbvtVolume ab,ba;
    Merge(a,b,ab); Merge(b,a,ba);
    for(int j=0;j<2;++j) for(int i=0;i<6;++i) {
        const auto& v=j?ba:ab;
        float value=i<3?v.Mins()[i]:v.Maxs()[i-3];
        std::memcpy(result+1+j*6+i,&value,sizeof(value));
    }
}
