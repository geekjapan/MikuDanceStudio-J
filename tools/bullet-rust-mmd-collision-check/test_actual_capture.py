"""Hosted entry reserved for legal actual-capture admission before malformed peers."""
import argparse
from evidence import admit_capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True)
    args = parser.parse_args()
    admit_capture(args.capture)


if __name__ == '__main__':
    main()
