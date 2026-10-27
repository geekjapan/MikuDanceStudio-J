#include <cstdio>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
extern "C" void replay_public();
extern "C" void replay_mmd();
extern "C" void replay_offsets();
int main() {
#ifdef _WIN32
  _setmode(_fileno(stdout),_O_BINARY);
#endif
  replay_public();replay_mmd(); replay_offsets();
}
