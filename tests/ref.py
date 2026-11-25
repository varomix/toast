# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Pure-Python references for Blender's hash functions (noise.cc), used by the tests."""

import struct

import numpy as np

M = 0xFFFFFFFF


def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & M


def _final(a, b, c):
    c ^= b; c = (c - _rot(b, 14)) & M
    a ^= c; a = (a - _rot(c, 11)) & M
    b ^= a; b = (b - _rot(a, 25)) & M
    c ^= b; c = (c - _rot(b, 16)) & M
    a ^= c; a = (a - _rot(c, 4)) & M
    b ^= a; b = (b - _rot(a, 14)) & M
    c ^= b; c = (c - _rot(b, 24)) & M
    return a, b, c  # fmt: skip


def hash1(kx):
    a = b = c = (0xDEADBEEF + (1 << 2) + 13) & M
    a = (a + (int(kx) & M)) & M
    return _final(a, b, c)[2]


def hash2(kx, ky):
    a = b = c = (0xDEADBEEF + (2 << 2) + 13) & M
    b = (b + (int(ky) & M)) & M
    a = (a + (int(kx) & M)) & M
    return _final(a, b, c)[2]


def uint_to_float_01(k):
    return np.float32(k) / np.float32(0xFFFFFFFF)


def float_bits(f):
    return struct.unpack("<I", struct.pack("<f", float(np.float32(f))))[0]


def rand_int(x):
    """toast rand(int) = hash_to_float(uint32(x))."""
    return uint_to_float_01(hash1(x))


def rand_float(x):
    """toast rand(float) = hash_float_to_float(x)."""
    return uint_to_float_01(hash1(float_bits(x)))


def random(id_, seed):
    """toast random(id, seed) = Random Value node (Float, 0..1) = hash_to_float(seed, id)."""
    return uint_to_float_01(hash2(seed, id_))
