#!/usr/bin/env python3
"""Operation streams for the real Bullet body oracle."""
import struct


def emit(op, *values):
    print(op, *(struct.pack('>f', v).hex() for v in values))


IDENTITY = (1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.)
ROTATED = (0., -1., 0., 1., 0., 0., 0., 0., 1., 2., -3., 1.)
SKEW = (.9, -.2, .17, .3, 1.1, -.1, .07, .2, .8, -.7, 2.3, 4.1)
PI_HALF = struct.unpack('>f', bytes.fromhex('3fc90fdb'))[0]


def main():
    for kind in range(4):
        for mass in (0., .7, 1., 3.1):
            for basis in (IDENTITY, ROTATED, SKEW):
                for damping in ((-.2, 1.2), (.17, .33), (-0., 0.)):
                    emit('N', mass, *damping, kind, .73, 1.17, .41, *basis, 0., 0., 0., 0.)
                    emit('G', 1.234567, -9.81, -0.)
                    emit('A')
                    emit('F', .1, -.3, .7)
                    emit('F', -.09, .31, -.2)
                    emit('T', .13, -.27, .39)
                    emit('T', -.3, .2, -.1)
                    emit('L', -0., .0000001, -.00001)
                    emit('W', .001, -.003, .007)
                    for dt in (1. / 60., .03):
                        emit('I', dt)
                        emit('D', dt)
                        emit('P', dt)
                    emit('C', *ROTATED)
                    emit('K', 1.)
                    emit('C', *SKEW)
                    emit('A')
                    emit('I', .02)
                    emit('D', .02)
                    emit('M', 0., 0., -.0, 3.7)
                    emit('G', -.31, 7.1, -.0)
                    emit('U')
                    emit('C', *IDENTITY)
                    emit('M', .7, 1.3, 0., 2.1)
                    emit('U')
                    emit('K', 0.)
                    emit('A')
                    emit('I', .02)
                    emit('Z')
                    emit('I', .02)
    for speed in (PI_HALF - 2**-23, PI_HALF, PI_HALF + 2**-23, 1000., .00001, 0., -0.):
        for mass in (0., .7):
            emit('N', mass, .23, .79, 0., .7, 0., 0., *SKEW, 1., 1.3, 0., 2.7)
            emit('L', -0., 0., -.0000001)
            emit('W', speed, 0., -0.)
            emit('I', 1.)
            emit('P', 1.)
            emit('D', .13)
            emit('C', *ROTATED)
            emit('K', 1.)
            emit('M', .31, 0., 2.1, -0.)
            emit('U')
            emit('I', .13)
            emit('K', 0.)
            emit('I', .13)
    for kind in range(4):
        for mass in (-.7, 0., .31):
            for inertia in ((0., 0., 0.), (0., 1.7, -0.), (.13, -0., 2.9)):
                emit('N', mass, .27, .43, kind, .71, 1.3, .47, *ROTATED, 1., *inertia)
                emit('G', -.0, .00001, -7.3)
                emit('F', -.0, .13, -.27)
                emit('T', .29, -.31, .47)
                emit('L', -0., .000001, -.000007)
                emit('W', -.000001, 0., -.0)
                emit('I', .007)
                emit('D', 0.)
                emit('P', .007)
                emit('D', 1.)
                emit('C', *SKEW)
                emit('I', .13)
    # Gravity force intentionally stays stale across mass changes until setGravity.
    emit('N', 0., 0., 0., 3., 0., 1., 0., *IDENTITY, 0., 0., 0., 0.)
    emit('G', -.0, -9.81, .1)
    emit('M', .7, 1., 2., 3.)
    emit('A')
    emit('G', .1, -9.81, -.0)
    emit('A')
    emit('M', 0., 0., 0., 0.)
    emit('G', 100., 200., 300.)
    emit('M', 3.1, 0., 0., 0.)
    emit('A')


if __name__ == '__main__':
    main()
