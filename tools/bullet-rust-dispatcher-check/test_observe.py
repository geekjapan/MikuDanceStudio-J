import unittest
from observe import instrument_rust, simplex_events
from pathlib import Path


class ObserverTests(unittest.TestCase):
    def test_actual_argument_is_observed_without_replacing_it(self):
        source = (Path(__file__).parents[2] / 'rust/crates/mds-bullet/src/core/dispatcher.rs').read_text()
        changed = source.replace('&mut self.simplex,', '&mut VoronoiSimplexSolver::default(),')
        observed = instrument_rust(changed)
        self.assertIn('let used_simplex = &mut VoronoiSimplexSolver::default();', observed)
        self.assertNotIn('let used_simplex = &mut self.simplex;', observed)
        self.assertEqual(simplex_events(b'ALLOC 0\nSIMPLEX 0\n'), ['SIMPLEX 0'])

    def test_malformed_observation_is_rejected(self):
        with self.assertRaises(AssertionError): simplex_events(b'SIMPLEX 1 fabricated\n')


if __name__ == '__main__': unittest.main()
