# Tiling (a library: Text "toast_lib.tiling"): 2D coordinates on any object, and hexagons.


def box_uv(p: vec3, n: vec3):
    """Coordinates on the side of a box the normal points to: each face gets the two axes along
    it, like the Image Texture node's Box projection."""
    a = abs(n)
    if a.z >= a.x and a.z >= a.y:
        return vec2(p.x, p.y)
    if a.x >= a.y:
        return vec2(p.y, p.z)
    return vec2(p.x, p.z)


def hex_cell(uv: vec2):
    """vec4(x, y, cell x, cell y): the position inside the nearest hexagon of a honeycomb (pointy
    side up, 1 across) and that hexagon's center."""
    s = vec2(1.0, 1.7320508)
    ca = (floor(uv / s) + 0.5) * s
    cb = (floor((uv - s * 0.5) / s) + 0.5) * s + s * 0.5
    a = uv - ca
    b = uv - cb
    if dot(a, a) < dot(b, b):
        return vec4(a.x, a.y, ca.x, ca.y)
    return vec4(b.x, b.y, cb.x, cb.y)


def hex_edge(q: vec2):
    """Distance from the center of a hexagon to its border along q: 0.5 on the border."""
    a = abs(q)
    return max(a.x, dot(a, vec2(0.5, 0.8660254)))
