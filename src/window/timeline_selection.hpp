#pragma once

namespace mikudancestudio {
class MMDApp;

int CompareFunction(const void* a, const void* b);
void ClearGlobalTimelineKeySelection(MMDApp& app);

// The four global tracks and every accessory track are allocated by UI init.
// Caller clears timeline selection counts before collecting new records.
void CollectGlobalTimelineSelection(MMDApp& app);
}
