# Cells (a library: Text "toast_lib.cells"): the two nearest of the random points scattered one
# per unit cell, for cracks, stones and scales. Shared by the lava rock and the lava flow.


def cell_point(cell: vec3, jitter):
    """The random point of a unit cell."""
    h = vec3(hash01(cell), hash01(cell + 17.13), hash01(cell + 41.71))
    return cell + 0.5 + (h - 0.5) * jitter


def cells(p: vec3, jitter):
    """vec3(f1, f2, id): distances to the nearest and second nearest points, and a random number
    for the nearest one's cell. f2 - f1 is 0 on the border between two cells: the cracks."""
    base = floor(p)
    f1 = 9.0
    f2 = 9.0
    id = 0.0
    for i in range(27):
        o = vec3(float(i % 3 - 1), float((i // 3) % 3 - 1), float(i // 9 - 1))
        d = distance(p, cell_point(base + o, jitter))
        if d < f1:
            f2 = f1
            f1 = d
            id = hash01(base + o + 5.3)
        elif d < f2:
            f2 = d
    return vec3(f1, f2, id)
