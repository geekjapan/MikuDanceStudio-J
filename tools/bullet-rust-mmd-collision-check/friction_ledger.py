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
        self.result_inserted = False
        self.result_constructed = False
        self.allocation = None
        self.ctor_pending = False
        self.operation = None
        self.previous_snapshot = None
        self.snapshot_order = []
        self.fixture = None
        self.fixture_expected = None
        self.fixture_checkpoint = None
        self.refresh = None
        self.refresh_expected = None
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

    def order(self, tag, site=None):
        if self.operation == 'W':
            require(tag not in ('FM', 'FC', 'FPY', 'FI', 'FX', 'FV', 'FR', 'FB', 'FT', 'FE', 'E')
                    and (tag != 'FW' or site == 'FIXTURE_W')
                    and (tag != 'FG' or site in ('COMMAND_BEGIN', 'COMMAND_END', 'FIXTURE_BEGIN',
                                                'FIXTURE_END', 'SNAPSHOT')),
                    'actual W has no intervening contact mutation')
        require(self.refresh_expected is None or self.refresh_expected == (tag, site),
                'exact refresh source order: expected ' + repr(self.refresh_expected))
        require(self.fixture_expected is None or self.fixture_expected == (tag, site),
                'exact fixture source order: expected ' + repr(self.fixture_expected))
        require(not self.ctor_pending or (tag, site) == ('FC', 'CTOR_GEOMETRIC'),
                'geometric constructor immediately binds FC')
        if self.allocation is not None:
            expected = ('FG', 'CTOR_EXIT') if self.allocation < 4 else (
                ('FG', 'MANIFOLD_ALLOC_EXIT') if self.allocation == 5 else ('FM', 'ALLOC'))
            require((tag, site) == expected or self.allocation == 4 and tag == 'E',
                    'exact four backing constructors and single allocation order')

    def complete_snapshot(self):
        require(len(self.snapshot_order) == len(self.manifolds)
                and set(self.snapshot_order) == set(self.manifolds), 'complete dispatcher snapshot order')
        self.previous_snapshot = tuple((mid, slot, gid) for mid in self.snapshot_order
                                       for slot, gid in enumerate(self.manifolds[mid][1]))
        self.snapshot_order = []

    def _fixture_event(self, cp, site):
        if site == 'FIXTURE_BEGIN':
            require(self.operation == 'W' and self.fixture_checkpoint != cp
                    and self.fixture is None and self.previous_snapshot is not None
                    and not self.transactions and not self.clearing and self.pending_move is None
                    and self.refresh is None, 'fixture BEGIN binds actual W and preceding complete snapshot')
            require(set(self.previous_snapshot) == {(mid, slot, gid) for mid, (_, slots) in self.manifolds.items()
                                                     for slot, gid in enumerate(slots)},
                    'fixture freezes every current live contact without intervening mutation')
            if self.native:
                require(self.scopes == ['FIXTURE'] and self.last_guard == 'FIXTURE_BEGIN',
                        'native fixture guard immediately wraps FF BEGIN')
            self.fixture = list(self.previous_snapshot)
            self.fixture_checkpoint = cp
        else:
            require(self.fixture == [], 'fixture END requires all exact ordered visits once')
            if self.native:
                self.fixture_expected = ('FG', 'FIXTURE_END')
                return
            self.fixture = None
            self.fixture_expected = None
            return
        self.fixture_expected = ('FW', 'FIXTURE_W') if self.fixture else ('FF', 'FIXTURE_END')

    def _refresh_next(self):
        self.refresh['pending'] = None
        self.refresh['cursor'] -= 1
        self.refresh_expected = ('FR', 'REFRESH_POINT' if self.refresh['cursor'] >= 0 else 'REFRESH_END')

    def _refresh_event(self, site, v):
        mid, slot, gid, distance, lateral = v
        require(type(mid) is int and mid > 0 and type(slot) is int and 0 <= slot <= 3
                and type(gid) is int and type(distance) is bool and type(lateral) is bool
                and not (distance and lateral), 'typed refresh binding and taken branch')
        if site == 'REFRESH_BEGIN':
            require(self.refresh is None and mid in self.manifolds
                    and not self.transactions and not self.clearing and self.pending_move is None,
                    'single refresh of live idle manifold')
            if self.native:
                require(self.scopes and self.scopes[-1] == 'REFRESH'
                        and self.last_guard == 'REFRESH_ENTER', 'native refresh entry immediately before BEGIN')
            require((slot, gid, distance, lateral) == (0, 0, False, False), 'exact refresh BEGIN/END sentinels')
            initial = tuple(self.manifolds[mid][1])
            self.refresh = dict(mid=mid, cursor=len(initial), initial=initial, visited=set(), pending=None)
            self._refresh_next()
        else:
            require(self.refresh is not None and mid == self.refresh['mid'], 'same active refresh manifold')
            if site == 'REFRESH_POINT':
                cursor = self.refresh['cursor']
                require(slot == cursor and cursor >= 0 and gid == self.refresh['initial'][cursor]
                        and gid not in self.refresh['visited'], 'descending initial-count refresh visits')
                self._binding(mid, slot, gid)
                self.refresh['visited'].add(gid)
                self.refresh['pending'] = (mid, slot, gid)
                if distance or lateral:
                    self.refresh_expected = ('FG', 'REMOVE_ENTER') if self.native else ('FX', 'REMOVE')
                elif self.native:
                    self.refresh_expected = ('FG', 'PROCESSED_PRECALL')
                else:
                    self._refresh_next()
            else:
                require(site == 'REFRESH_END' and (slot, gid, distance, lateral) == (0, 0, False, False),
                        'exact refresh BEGIN/END sentinels')
                require(self.refresh['cursor'] == -1 and self.refresh['pending'] is None
                        and len(self.refresh['visited']) == len(self.refresh['initial']), 'complete refresh visits')
                if self.native:
                    self.refresh_expected = ('FG', 'REFRESH_EXIT')
                else:
                    self.refresh = self.refresh_expected = None

    def guard(self, cp, site, values):
        require(self.native, 'guards belong to native observed')
        self.order('FG', site)
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
                    require(self.operation != 'W' or self.fixture_checkpoint == cp and self.fixture is None
                            and self.fixture_expected is None, 'complete fixture before W snapshot')
                    self.snapshot_guard = True
                elif site.endswith('_ENTER') or site in ('SOLVER_BEGIN', 'FIXTURE_BEGIN'):
                    scope = site.rsplit('_', 1)[0]
                    if scope == 'RESULT':
                        require('RESULT' not in self.scopes, 'single actual Result scope')
                        self.result_inserted = False
                        self.result_constructed = False
                    elif scope == 'MANIFOLD_ALLOC':
                        require(self.allocation is None, 'single manifold allocation scope')
                        self.allocation = 0
                    elif scope == 'FIXTURE':
                        require(self.operation == 'W' and not self.scopes and self.fixture is None,
                                'fixture guard in actual W')
                        self.fixture_expected = ('FF', 'FIXTURE_BEGIN')
                    elif scope == 'REFRESH':
                        require(self.refresh is None and self.refresh_expected is None
                                and self.cache_closures == 0, 'single idle native refresh entry')
                        self.refresh_expected = ('FR', 'REFRESH_BEGIN')
                    require(len(self.scopes) < 256, 'guard scope capacity')
                    self.scopes.append(scope)
                    self.maxima['scopes'] = max(self.maxima['scopes'], len(self.scopes))
                elif site.endswith('_EXIT') and site != 'CTOR_EXIT' or site in ('SOLVER_END', 'FIXTURE_END'):
                    scope = site.rsplit('_', 1)[0]
                    require(self.scopes and self.scopes[-1] == scope, 'properly nested guard exit')
                    self.scopes.pop()
                    if scope == 'USERCACHE':
                        self.cache_closures += 1
                    elif scope == 'RESULT':
                        require(self.pending_added is None and self.result_constructed == self.result_inserted,
                                'Result exit consumes constructor and insertion callback')
                    elif scope == 'MANIFOLD_ALLOC':
                        require(self.allocation == 5, 'allocation exit after four constructors and single FM')
                        self.allocation = None
                    elif scope == 'FIXTURE':
                        require(self.fixture == [] and self.fixture_expected == ('FG', site),
                                'native fixture exit after complete FF END')
                        self.fixture = self.fixture_expected = None
                    elif scope == 'REFRESH':
                        require(self.refresh is not None and self.refresh_expected == ('FG', 'REFRESH_EXIT'),
                                'refresh exit after complete END')
                        self.refresh = self.refresh_expected = None
                elif site == 'CTOR_EXIT':
                    if self.scopes and self.scopes[-1] == 'MANIFOLD_ALLOC':
                        require(self.allocation is not None and self.allocation < 4,
                                'exact four backing constructors')
                        self.allocation += 1
                    else:
                        require(self.scopes == ['RESULT'] and not self.result_constructed,
                                'one geometric constructor inside actual Result call')
                        self.result_constructed = True
                        self.ctor_pending = True
                else:
                    if site == 'ADDED_PRECALL':
                        require(self.pending_added is not None, 'Added precall binds immediately preceding insertion')
                        self._binding(*self.pending_added)
                        self.pending_added = None
                    elif site == 'DESTROYED_PRECALL':
                        require('USERCACHE' in self.scopes, 'Destroyed precall usercache scope')
                    elif site == 'PROCESSED_PRECALL':
                        require(self.refresh is not None and self.refresh_expected == ('FG', site)
                                and self.refresh['pending'] is not None, 'Processed precall binds kept refresh point')
                        self._binding(*self.refresh['pending'])
                        self._refresh_next()
        if self.refresh is not None:
            following = {'REMOVE_ENTER': ('FG', 'USERCACHE_ENTER'),
                         'USERCACHE_ENTER': ('FG', 'USERCACHE_EXIT'),
                         'USERCACHE_EXIT': ('FX', 'REMOVE')}
            if site in following:
                self.refresh_expected = following[site]
            elif site == 'REMOVE_EXIT':
                self._refresh_next()

    def event(self, cp, tag, site, v):
        self.order(tag, site)
        if self.native:
            require(self.started and self.command == cp, 'native event within guarded command')
            require(self.pending_added is None, 'mandatory post-insertion Added precall guard')
        if self.pending_move is not None:
            require(tag == 'FV', 'immediate mandatory remove/move-last event')
        if tag == 'FF':
            self._fixture_event(cp, site)
        elif tag == 'FR':
            self._refresh_event(site, v)
        elif tag == 'FM':
            mid, a, b = v
            if site == 'ALLOC':
                if self.native:
                    require(self.scopes and self.scopes[-1] == 'MANIFOLD_ALLOC' and self.allocation == 4,
                            'allocation requires four actual backing constructors')
                    self.allocation = 5
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
                require(site == 'CTOR_GEOMETRIC' and self.ctor_pending and self.last_guard == 'CTOR_EXIT'
                        and self.scopes == ['RESULT'], 'initialized geometric constructor exit immediately before incoming generation')
                self.ctor_pending = False
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
            if self.native:
                require(len(self.scopes) >= 2 and self.scopes[-2:] ==
                        ['RESULT', 'REPLACE' if site == 'REPLACE' else 'ADD']
                        and not self.result_inserted, 'one insertion directly nested in actual Result call')
                self.result_inserted = True
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
                if self.refresh is not None:
                    require(site == 'REMOVE' and (mid, slot, gid) == self.refresh['pending'],
                            'refresh removal binds exact pending point')
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
                if self.refresh is not None:
                    if self.pending_move is not None:
                        self.refresh_expected = ('FV', 'REMOVE_MOVE')
                    elif self.native:
                        self.refresh_expected = ('FG', 'REMOVE_EXIT')
                    else:
                        self._refresh_next()
        elif tag == 'FV':
            require(self.pending_move == v, 'exact remove/move-last transfer')
            self._binding(v[0], v[2], v[3])
            self.pending_move = None
            if self.refresh is not None:
                if self.native:
                    self.refresh_expected = ('FG', 'REMOVE_EXIT')
                else:
                    self._refresh_next()
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
                require(self.fixture and self.fixture[0] == (mid, slot, gid),
                        'fixture write matches next exact dispatcher/slot/generation visit')
                self.fixture.pop(0)
                self.fixture_expected = ('FW', 'FIXTURE_W') if self.fixture else ('FF', 'FIXTURE_END')
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
        self.order('FS', 'SNAPSHOT')
        require(self.pending_move is None and not self.transactions and not self.clearing,
                'snapshot after complete mutations')
        require(self.pending_added is None and self.cache_closures == 0, 'snapshot after exact insertion/cache guard closure')
        require(mid in self.manifolds and self.manifolds[mid] == (body_pair, slots),
                'snapshot matches complete ordered live manifold')
        if self.native:
            require(self.snapshot_guard and not self.scopes, 'guard before safe native snapshot')
        require(mid not in self.snapshot_order, 'one manifold in dispatcher snapshot order')
        self.snapshot_order.append(mid)

    def finish(self, commands):
        require(not self.manifolds and not self.points and not self.temporary and not self.transactions
                and not self.clearing and not self.releasing and self.pending_move is None and not self.scopes,
                'closed manifold/generation/temporary/transaction lifetimes')
        require(self.refresh is None and self.refresh_expected is None, 'closed refresh lifetime')
        require(self.allocation is None and not self.ctor_pending and self.fixture is None
                and self.fixture_expected is None, 'closed allocation/constructor/fixture lifetime')
        if self.native:
            require(self.started and self.command is None and self.command_ended == commands - 1,
                    'complete guarded command schedule')
