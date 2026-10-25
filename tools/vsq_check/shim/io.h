// CRT <io.h> names the file uses; POSIX has them without the underscore.
#pragma once
#include <unistd.h>
#define _read ::read
#define _close ::close
