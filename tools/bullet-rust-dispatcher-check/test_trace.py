import unittest
from trace import validate
from cases import corpus


class TraceTests(unittest.TestCase):
    def test_complete_empty_trace(self):
        validate(b'O 0 F 0 0\nZ 1\n', b'F\n')

    def test_truncated_and_extra_output_are_rejected(self):
        for raw in [b'O 0 F 0 0\n', b'O 0 F 0 0\nZ 1\nnoise\n']:
            with self.assertRaises((AssertionError, StopIteration)):
                validate(raw, b'F\n')

    def test_all_ordered_shape_pairs_are_inputs(self):
        source = corpus().decode().splitlines()
        pairs = set()
        shapes = {}
        for line in source:
            p = line.split()
            if p[0] == 'F': shapes = {}
            if p[0] == 'N': shapes[int(p[1])] = int(p[2])
            if p[0] == 'P' and len(shapes) == 2: pairs.add((shapes[int(p[1])], shapes[int(p[2])]))
        self.assertEqual(pairs, {(a, b) for a in range(4) for b in range(4)})


if __name__ == '__main__': unittest.main()
