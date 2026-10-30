"""Reconstruct logical writes independently of received validity assertions."""
from friction_schema import require

WRITE_MASK = {'DIR1_RAW': 1, 'VELOCITY_DIR1': 1, 'VELOCITY_DIR2': 2,
              'PLANE_BOTH': 3, 'ANISO_DIR1': 1, 'ANISO_DIR2': 2, 'FIXTURE_W': 3}


class Ledger:
    def __init__(self, native):
        self.native = native
        self.manifolds = {}
        self.points = {}
        self.temporary = {}
        self.used_mid = set()
        self.used_gid = set()
        self.used_transaction = set()
        self.transactions = {}
        self.clearing = {}
        self.releasing = {}
        self.pending_move = None
        self.closed = 0
        self.maxima = dict(manifolds=0, points=0, temporary=0, scopes=0)
        self.scopes = []
        self.started = False
        self.command = None
        self.command_ended = -1
        self.snapshot_guard = False
        self.last_guard = None
        self.pending_added = None
        self.pending_added_exit = None
        self.cache_closures = 0
        self.history = []

    def _fresh(self, value, used, name):
        require(value not in used, 'fresh ' + name)
        used.add(value)

    def _open(self, gid, mask, temporary):
        self._fresh(gid, self.used_gid, 'generation')
        target = self.temporary if temporary else self.points
        require(len(target) < (256 if temporary else 16384), 'generation capacity')
        target[gid] = mask
        self.maxima['temporary' if temporary else 'points'] = max(
            self.maxima['temporary' if temporary else 'points'], len(target))

    def _close(self, gid, temporary=False):
        require(gid not in self.transactions, 'close after transaction')
        target = self.temporary if temporary else self.points
        require(gid in target, 'close live generation')
        del target[gid]
        self.closed += 1

    def _binding(self, mid, slot, gid):
        require(mid in self.manifolds and slot < len(self.manifolds[mid][1])
                and self.manifolds[mid][1][slot] == gid and gid in self.points,
                'exact live manifold/slot/generation binding')

    def _scope(self, name):
        if self.native:
            require(name in self.scopes, 'required native guard scope ' + name)

    def guard(self, cp, site, values):
        require(self.native, 'guards belong to native observed')
        require(self.pending_move is None, 'immediate mandatory remove/move-last event')
        require(all(type(value) is bool for value in values) and values == (True, True, True, True),
                'null Added/Processed/Destroyed/usercache guard')
        if self.pending_added is not None:
            require(site == (self.pending_added_exit or 'ADDED_PRECALL'), 'exact insertion exit then Added precall guard order')
            if self.pending_added_exit is not None:
                self.pending_added_exit = None
        self.last_guard = site
        if site == 'STARTUP':
            require(not self.started and cp == 0 and not self.scopes, 'single startup guard')
            self.started = True
        else:
            require(self.started, 'startup before guards')
            if site == 'COMMAND_BEGIN':
                require(self.command is None and cp == self.command_ended + 1 and not self.scopes,
                        'ordered command begin guard')
                self.command = cp
                self.snapshot_guard = False
            else:
                require(self.command == cp, 'guard in current command')
                if site == 'COMMAND_END':
                    require(not self.scopes and self.snapshot_guard and self.pending_added is None
                            and self.cache_closures == 0, 'closed scopes and snapshot before command end')
                    self.command = None
                    self.command_ended = cp
                elif site == 'SNAPSHOT':
                    require(not self.scopes and not self.snapshot_guard and self.pending_added is None
                            and self.cache_closures == 0, 'one snapshot guard outside mutation')
                    self.snapshot_guard = True
                elif site.endswith('_ENTER') or site in ('SOLVER_BEGIN', 'FIXTURE_BEGIN'):
                    scope = site.rsplit('_', 1)[0]
                    require(len(self.scopes) < 256, 'guard scope capacity')
                    self.scopes.append(scope)
                    self.maxima['scopes'] = max(self.maxima['scopes'], len(self.scopes))
                elif site.endswith('_EXIT') and site != 'CTOR_EXIT' or site in ('SOLVER_END', 'FIXTURE_END'):
                    scope = site.rsplit('_', 1)[0]
                    require(self.scopes and self.scopes[-1] == scope, 'properly nested guard exit')
                    self.scopes.pop()
                    if scope == 'USERCACHE':
                        self.cache_closures += 1
                elif site == 'CTOR_EXIT':
                    pass
                else:
                    if site == 'ADDED_PRECALL':
                        require(self.pending_added is not None, 'Added precall binds immediately preceding insertion')
                        self._binding(*self.pending_added)
                        self.pending_added = None
                    elif site == 'DESTROYED_PRECALL':
                        require('USERCACHE' in self.scopes, 'Destroyed precall usercache scope')

    def event(self, cp, tag, site, v):
        if self.native:
            require(self.started and self.command == cp, 'native event within guarded command')
            require(self.pending_added is None, 'mandatory post-insertion Added precall guard')
        if self.pending_move is not None:
            require(tag == 'FV', 'immediate mandatory remove/move-last event')
        if tag == 'FM':
            mid, a, b = v
            if site == 'ALLOC':
                require(a != b and len(self.manifolds) < 4096, 'bounded manifold with distinct body pair')
                self._fresh(mid, self.used_mid, 'manifold')
                self.manifolds[mid] = ((a, b), [])
                self.maxima['manifolds'] = max(self.maxima['manifolds'], len(self.manifolds))
            else:
                require(mid in self.manifolds and self.manifolds[mid][0] == (a, b), 'persistent manifold body binding')
                if site == 'CLEAR_BEGIN':
                    self._scope('CLEAR')
                    require(mid not in self.clearing, 'one clear transaction')
                    self.clearing[mid] = list(self.manifolds[mid][1])
                elif site == 'CLEAR_END':
                    self._scope('CLEAR')
                    require(mid in self.clearing and not self.clearing[mid], 'complete ordered clear point closure')
                    del self.clearing[mid]
                    self.manifolds[mid][1].clear()
                else:
                    self._scope('RELEASE')
                    require(all(gid not in self.points for gid in self.manifolds[mid][1])
                            and mid not in self.clearing, 'release after all point closures')
                    if mid in self.releasing:
                        require(self.releasing[mid] == len(self.manifolds[mid][1]), 'complete ordered release point closure')
                        del self.releasing[mid]
                    del self.manifolds[mid]
        elif tag == 'FC':
            require((site != 'RUST_CONTACT_CREATE') == self.native, 'language-specific contact construction')
            if self.native:
                require(self.last_guard == 'CTOR_EXIT', 'initialized constructor exit guard before incoming generation')
            self._open(v[0], 0, True)
        elif tag == 'FPY':
            source, copied, mask = v
            require(source in self.points or source in self.temporary, 'tracked copy source')
            actual = self.points[source] if source in self.points else self.temporary[source]
            require(mask == actual, 'copy inherits independently reconstructed validity')
            self._open(copied, actual, True)
        elif tag == 'FI':
            mid, slot, old, incoming, new, mask = v
            self._scope('REPLACE' if site == 'REPLACE' else 'ADD')
            require(mid in self.manifolds and mid not in self.clearing, 'insert in live manifold')
            require(incoming in self.temporary and self.temporary[incoming] == mask, 'independent incoming validity')
            require(len({old, incoming, new}) == 3 and new not in self.used_gid, 'distinct fresh insertion generations')
            slots = self.manifolds[mid][1]
            if site == 'ADD':
                require(old == 0 and slot == len(slots) and len(slots) < 4, 'append next unused slot')
            else:
                require((site != 'EVICT_ADD' or len(slots) == 4), 'eviction requires full cache')
                self._binding(mid, slot, old)
                if self.native and site == 'EVICT_ADD':
                    require(self.cache_closures == 1, 'eviction closes guarded old usercache')
                    self.cache_closures = 0
                self._close(old)
            self._close(incoming, True)
            self._open(new, mask, False)
            if site == 'ADD':
                slots.append(new)
            else:
                slots[slot] = new
            if self.native:
                self.pending_added = (mid, slot, new)
                self.pending_added_exit = 'REPLACE_EXIT' if site == 'REPLACE' else 'ADD_EXIT'
        elif tag == 'FX':
            mid, slot, gid = v
            if site == 'TEMP_END':
                require(mid == slot == 0, 'temporary has no manifold binding')
                self._close(gid, True)
            else:
                self._binding(mid, slot, gid)
                if self.native:
                    require(self.cache_closures == 1, 'guarded usercache closure before point closure')
                    self.cache_closures = 0
                slots = self.manifolds[mid][1]
                if site == 'REMOVE':
                    self._scope('REMOVE')
                    require(mid not in self.clearing, 'remove outside clear')
                    if slot != len(slots) - 1:
                        self.pending_move = (mid, len(slots) - 1, slot, slots[-1])
                        slots[slot] = slots[-1]
                    slots.pop()
                elif site == 'CLEAR_POINT':
                    self._scope('CLEAR')
                    require(mid in self.clearing and self.clearing[mid] and self.clearing[mid][0] == gid,
                            'clear point in actual forward order')
                    self.clearing[mid].pop(0)
                else:
                    self._scope('RELEASE')
                    require(mid not in self.clearing and slot == self.releasing.get(mid, 0),
                            'release point in actual forward order')
                    self.releasing[mid] = slot + 1
                self._close(gid)
        elif tag == 'FV':
            require(self.pending_move == v, 'exact remove/move-last transfer')
            self._binding(v[0], v[2], v[3])
            self.pending_move = None
        elif tag == 'FB':
            mid, slot, gid, transaction, mode, flag = v
            self._scope('SOLVER')
            self._binding(mid, slot, gid)
            require(gid not in self.transactions, 'one active transaction per contact')
            self._fresh(transaction, self.used_transaction, 'solver transaction')
            require(mode == 260 if not self.native else mode & ~1023 == 0,
                    'supported independently frozen solver mode')
            self.transactions[gid] = dict(binding=(mid, slot, gid, transaction), mode=mode,
                                          flag=flag, choice=None, writes=[], mask=0)
        elif tag in ('FT', 'FW', 'FE'):
            mid, slot, gid, transaction = v[:4]
            self._binding(mid, slot, gid)
            if tag == 'FW' and site == 'FIXTURE_W':
                self._scope('FIXTURE')
                require(transaction == 0 and v[4] == 3 and gid not in self.transactions,
                        'fixture write outside solver transaction')
                self.points[gid] |= 3
            else:
                self._scope('SOLVER')
                require(gid in self.transactions, 'active solver transaction')
                tx = self.transactions[gid]
                require(tx['binding'] == v[:4], 'exact transaction binding')
                if tag == 'FT':
                    recompute, velocity, two = v[4:]
                    require(tx['choice'] is None and (recompute or not velocity), 'one lawful branch choice')
                    if self.native:
                        require(recompute == (not bool(tx['mode'] & 32) or not tx['flag'])
                                and two == bool(tx['mode'] & 16), 'actual mode/flag branch consistency')
                        require(not velocity or not tx['mode'] & 64, 'actual velocity branch enabled')
                        require(tx['writes'] == (['DIR1_RAW'] if recompute else []), 'raw write before native condition record')
                    else:
                        require(recompute and not two and not tx['writes'], 'independent Rust branch model')
                    if not recompute:
                        needed = 3 if two else 1
                        require(self.points[gid] & needed == needed, 'cached direction reads require prior lawful writes')
                    tx['choice'] = (recompute, velocity, two)
                elif tag == 'FW':
                    require(site != 'FIXTURE_W' and v[4] == WRITE_MASK[site], 'exact writer mask')
                    require(site == 'DIR1_RAW' and self.native and tx['choice'] is None and not tx['writes']
                            or tx['choice'] is not None and tx['choice'][0] and site != 'DIR1_RAW',
                            'writer in independently observed branch')
                    require(self.native or site in ('VELOCITY_DIR1', 'PLANE_BOTH'), 'independent Rust writer sites')
                    tx['writes'].append(site)
                    tx['mask'] |= WRITE_MASK[site]
                    self.points[gid] |= WRITE_MASK[site]
                else:
                    require(tx['choice'] is not None, 'branch choice before transaction completion')
                    recompute, velocity, two = tx['choice']
                    expected_site = ('VELOCITY' if velocity else 'PLANE') if recompute else 'CACHED'
                    expected_site += '_TWO' if two else '_ONE'
                    require(site == expected_site, 'branch completion matches actual condition observations')
                    mandatory = []
                    if recompute:
                        if self.native:
                            mandatory.append('DIR1_RAW')
                        mandatory.append('VELOCITY_DIR1' if velocity else 'PLANE_BOTH')
                        if self.native and velocity and two:
                            mandatory.append('VELOCITY_DIR2')
                    # Anisotropy writes need separate source-site capability evidence.
                    # The frozen MMD fixture has no anisotropic objects.
                    require(tx['writes'] == mandatory, 'complete source-ordered mandatory writer schedule')
                    require(v[4] == tx['mask'] and v[5] == self.points[gid], 'independently reconstructed branch/persistent masks')
                    require(v[6] == (True if recompute else tx['flag']), 'branch final legacy flag')
                    del self.transactions[gid]
        else:
            raise ValueError('known lifecycle/solver event')
        require(len(self.points) + len(self.temporary) <= 16384, 'active point/temporary binding capacity')
        self.last_guard = None
        self.history.append((cp, tag, site, v))

    def snapshot(self, mid, slots, body_pair):
        require(self.pending_move is None and not self.transactions and not self.clearing,
                'snapshot after complete mutations')
        require(self.pending_added is None and self.cache_closures == 0, 'snapshot after exact insertion/cache guard closure')
        require(mid in self.manifolds and self.manifolds[mid] == (body_pair, slots),
                'snapshot matches complete ordered live manifold')
        if self.native:
            require(self.snapshot_guard and not self.scopes, 'guard before safe native snapshot')

    def finish(self, commands):
        require(not self.manifolds and not self.points and not self.temporary and not self.transactions
                and not self.clearing and not self.releasing and self.pending_move is None and not self.scopes,
                'closed manifold/generation/temporary/transaction lifetimes')
        if self.native:
            require(self.started and self.command is None and self.command_ended == commands - 1,
                    'complete guarded command schedule')
