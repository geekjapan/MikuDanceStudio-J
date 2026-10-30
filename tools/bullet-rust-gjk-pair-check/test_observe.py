"""The observer must reject loss of fallback evidence in any ordered pair."""
from observe import PAIRS, require_fallback_coverage


def test_fallback_coverage():
    events = [f'outer-{branch} {a} {b}' for a, b in PAIRS
              for branch in ['penetration-adapter', 'distance-fallback', 'emitted']]
    assert len(require_fallback_coverage(events)) == 6
    for a, b in PAIRS:
        missing = f'outer-distance-fallback {a} {b}'
        try:
            require_fallback_coverage([event for event in events if event != missing])
        except AssertionError as error:
            assert PAIRS[a, b] in str(error)
        else:
            raise AssertionError(f'Accepted missing fallback evidence for {PAIRS[a, b]}')


if __name__ == '__main__':
    test_fallback_coverage()
