# Text "toast_lib.tree": helpers for the tree example (a Toast library: only defs).

def child_rotation(parent: quat, k, spread, seed):
    """Spin the k-th child around its parent's axis (golden angle), then tilt it outward."""
    spin = quat_axis_angle((0, 0, 1), k * 2.39996 + random(seed, 11) * 0.8)
    tilt = quat_axis_angle((1, 0, 0), spread * (0.6 + 0.8 * random(seed, 12)))
    return parent * spin * tilt


def bend_up(q: quat, amount):
    """Turn a branch's direction a little toward the sky (branches reach for light)."""
    up_now = rotate(q, (0, 0, 1))
    return slerp(q, quat_between(up_now, (0, 0, 1)) * q, amount)


def grown(growth, depth):
    """How much of a branch at this depth has grown, 0..1, when the tree's growth is `growth`."""
    return smoothstep(0.0, 1.0, growth - depth)


def leaf_scale(t, last):
    """Size of the leaf at a branch's tip, 0..1, when the branch is `t` levels into its growth
    (0..1 while it grows). A leaf grows in with its branch. When the branch is done and its
    children start growing (t from 1 to 1.5), it shrinks away while their leaves grow in, so
    leaves never pop. The last level's leaves stay."""
    grow_in = smoothstep(0.0, 0.5, t)
    if last:
        return grow_in
    return grow_in * (1.0 - smoothstep(1.0, 1.5, t))
