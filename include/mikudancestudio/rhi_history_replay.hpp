#pragma once
struct IDirect3DDevice9;
struct ID3DXMesh;
namespace mikudancestudio {
#ifdef MIKUDANCESTUDIO_DIAG
void BeginHistoryReplay(IDirect3DDevice9*,unsigned clearFlags,unsigned color,float z,unsigned stencil);
void RecordHistoryDraw(IDirect3DDevice9*,unsigned type,bool indexed,int base,unsigned minimum,unsigned vertices,unsigned start,unsigned count);
void RecordHistoryMesh(IDirect3DDevice9*,ID3DXMesh*,unsigned attribute);
void ResetHistoryReplay();
void BlockHistoryReplay(const char* reason);
void CompareHistoryReplay(IDirect3DDevice9*,unsigned slot,unsigned material,unsigned indices);
void CompleteHistoryReplay(IDirect3DDevice9*,unsigned material);
#else
inline void ResetHistoryReplay() {}
#endif
}
