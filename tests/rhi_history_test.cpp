#include "mikudancestudio/rhi.hpp"
#include <cstdio>
using namespace mikudancestudio::rhi;
int main() {
    HistoryDesc single;single.width=4;single.height=3;
    HistoryCapabilities transfer;transfer.colorCapture=transfer.depthCapture=transfer.stencilCapture=HistoryAccess::Native;
    transfer.colorRestore=transfer.depthRestore=transfer.stencilRestore=HistoryAccess::Native;
    transfer.maxSamples=8;
    if(!ValidHistoryDesc(single) || !CanCaptureHistory(transfer,single) || !CanRestoreHistory(transfer,single,single))return 1;
    auto sample=single;sample.samples=8;sample.representation=HistoryRepresentation::PerSample;sample.samplePattern=42;
    if(!ValidHistoryDesc(sample) || CanCaptureHistory(transfer,sample) || CanRestoreHistory(transfer,sample,sample))return 2;
    transfer.perSampleCapture=transfer.perSampleRestore=true;
    if(!CanCaptureHistory(transfer,sample) || !CanRestoreHistory(transfer,sample,sample))return 3;
    auto other=sample;other.samplePattern=43;if(CanRestoreHistory(transfer,sample,other))return 4;
    other=sample;other.quality=1;if(CanRestoreHistory(transfer,sample,other))return 5;
    auto resolved=sample;resolved.representation=HistoryRepresentation::ResolvedColor;resolved.depth=resolved.stencil=false;resolved.resolve=ColorResolveRule::Srgb;
    transfer.resolvedColorCapture=true;transfer.srgbResolve=true;
    if(!CanCaptureHistory(transfer,resolved) || CanRestoreHistory(transfer,resolved,sample) || CanRestoreHistory(transfer,resolved,single))return 6;
    resolved.depth=true;if(ValidHistoryDesc(resolved))return 7;
    resolved.depth=false;resolved.resolve=ColorResolveRule::LinearUnorm;if(CanCaptureHistory(transfer,resolved))return 8;
    transfer.completeDrawReplay=true;transfer.perSampleCapture=false;transfer.depthCapture=HistoryAccess::DrawReplay;
    if(CanCaptureHistory(transfer,sample) || CanCaptureHistory(transfer,single))return 9;
    HistoryData data;data.description=sample;data.rgba.resize(4*3*8*4);data.depthStencil.resize(4*3*8);
    if(!ValidHistoryData(data))return 10;
    data.depthStencil.pop_back();if(ValidHistoryData(data))return 11;
    data.description=single;data.rgba.resize(4*3*4);data.depthStencil.resize(4*3);
    auto null=CreateNullDevice();if(null->CaptureHistory(single,data)!=HistoryResult::Unsupported || !data.rgba.empty() ||
        null->HistoryFeatures().completeDrawReplay || null->RestoreHistory(single,data)!=HistoryResult::Unsupported)return 12;
    other=sample;other.samplePattern=0;if(ValidHistoryDesc(other))return 13;
    other=single;other.samples=3;if(ValidHistoryDesc(other))return 14;
    HistoryReplayBoundary replay;replay.target=sample;replay.eventCount=20;replay.startsAtClear=true;
    if(CanReplayHistory(transfer,replay))return 15;
    replay.allEventsRecorded=replay.allResourcesVersioned=replay.allEventsSupported=true;
    if(!CanReplayHistory(transfer,replay))return 16;
    replay.allResourcesVersioned=false;if(CanReplayHistory(transfer,replay))return 17;
    std::puts("History contract PASS: exact samples, attachments, resolve, pattern/quality, unsupported fallback");return 0;
}
