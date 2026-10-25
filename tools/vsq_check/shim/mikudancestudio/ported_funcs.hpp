// Declarations src/io/vsq_load.cpp takes from the real ported_funcs.hpp. A
// signature drift there shows up as a link error against the harness.
#pragma once
#include "mikudancestudio/model.hpp"

namespace mikudancestudio {
class MMDApp;
int ReadBeWord(int fh, int* outVal, int nbytes);
int ReadFixedString(int fh, char* out, int len);
void RegisterMorphKeyCurrent(unsigned char* model, int morph, int frame);
int SeekModelFrame(mdl::ModelRecord& model, int frame, int physicsMode);
void TimelineDrawTicks(int frameOffset, int width);
void AviBgOverlayRefresh(MMDApp*);
void PanelPaint(MMDApp* app);
}  // namespace mikudancestudio
