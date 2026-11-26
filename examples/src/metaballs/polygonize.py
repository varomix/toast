# Metaballs (Run Over: Geometry): marching cubes, written in Toast. Balls drift through a box;
# each adds a field that falls smoothly from 1 at its center to 0 at its reach (a lone ball's
# surface sits at its radius), and the surface is where the sum equals `threshold`, so balls
# melt together only when they come close. The box is cut into resolution^3 cubes, walked one z layer at a time: the field
# at the corners of two layers, and the surface points made on the cube edges so far, live in
# lists, so cubes sharing an edge share its point and the mesh comes out closed and connected.
# Every frame builds the whole mesh again from nothing.
from toast_lib.metaballs import tri_table, ball, falloff

TRI = tri_table()
count = clamp(param("balls", 8, min=1, max=16), 1, 16)
res = clamp(param("resolution", 56, min=4, max=60), 4, 60)
size = param("size", 4.0)
iso = param("threshold", 0.25)
seed = param("seed", 0)
spread = param("spread", 1.3)
speed = param("speed", 1.0)

centers = [vec3(0, 0, 0)] * 16
reach2 = [0.0] * 16         # squared reach of each ball
for b in range(count):
    c = ball(b, @time * speed, seed, spread)
    centers[b] = c.xyz
    reach2[b] = c.w * c.w / 0.37      # a lone ball's field is 0.25 at 0.61 x its reach

S = res + 1                 # corners per row
cell = size / res
lo = vec3(-0.5, -0.5, -0.5) * size

# Field at the corners of the bottom (fb) and top (ft) layer of the current row of cubes.
fb = [0.0] * 3721           # 61 x 61, enough for resolution 60
ft = [0.0] * 3721
# Surface points already made, by edge (-1 = none yet): x and y edges of the bottom and top
# layers, and the z edges between them. The point numbers are the ones add_point() gives.
xb = [-1] * 3660            # 60 x 61
yb = [-1] * 3660
xt = [-1] * 3660
yt = [-1] * 3660
ze = [-1] * 3721
next_point = point_count(0)

for k in range(res + 1):
    # Field values of corner layer k (the top of this row of cubes).
    z = lo.z + k * cell
    for j in range(S):
        for i in range(S):
            p = vec3(lo.x + i * cell, lo.y + j * cell, z)
            f = 0.0
            for b in range(count):
                d = p - centers[b]
                f += falloff(dot(d, d), reach2[b])
            ft[j * S + i] = f
    if k == 0:
        fb = ft
        continue
    z0 = z - cell
    for q in range(3660):
        xt[q] = -1
        yt[q] = -1
    for q in range(3721):
        ze[q] = -1

    for j in range(res):
        for i in range(res):
            a = j * S + i
            v0 = fb[a]
            v1 = fb[a + 1]
            v2 = fb[a + S + 1]
            v3 = fb[a + S]
            v4 = ft[a]
            v5 = ft[a + 1]
            v6 = ft[a + S + 1]
            v7 = ft[a + S]
            case = 0
            if v0 > iso:
                case += 1
            if v1 > iso:
                case += 2
            if v2 > iso:
                case += 4
            if v3 > iso:
                case += 8
            if v4 > iso:
                case += 16
            if v5 > iso:
                case += 32
            if v6 > iso:
                case += 64
            if v7 > iso:
                case += 128
            if case == 0 or case == 255:
                continue

            x0 = lo.x + i * cell
            y0 = lo.y + j * cell
            x1 = x0 + cell
            y1 = y0 + cell
            ex = j * res + i            # this cube's x edge at y0 (y1: + res)
            ey = j * S + i              # this cube's y edge at x0 (x1: + 1)
            edge = [-1] * 12
            # Bottom square: edges 0-3.
            if (v0 > iso) != (v1 > iso):
                if xb[ex] < 0:
                    add_point(vec3(x0 + cell * (iso - v0) / (v1 - v0), y0, z0))
                    xb[ex] = next_point
                    next_point += 1
                edge[0] = xb[ex]
            if (v1 > iso) != (v2 > iso):
                if yb[ey + 1] < 0:
                    add_point(vec3(x1, y0 + cell * (iso - v1) / (v2 - v1), z0))
                    yb[ey + 1] = next_point
                    next_point += 1
                edge[1] = yb[ey + 1]
            if (v3 > iso) != (v2 > iso):
                if xb[ex + res] < 0:
                    add_point(vec3(x0 + cell * (iso - v3) / (v2 - v3), y1, z0))
                    xb[ex + res] = next_point
                    next_point += 1
                edge[2] = xb[ex + res]
            if (v0 > iso) != (v3 > iso):
                if yb[ey] < 0:
                    add_point(vec3(x0, y0 + cell * (iso - v0) / (v3 - v0), z0))
                    yb[ey] = next_point
                    next_point += 1
                edge[3] = yb[ey]
            # Top square: edges 4-7.
            if (v4 > iso) != (v5 > iso):
                if xt[ex] < 0:
                    add_point(vec3(x0 + cell * (iso - v4) / (v5 - v4), y0, z))
                    xt[ex] = next_point
                    next_point += 1
                edge[4] = xt[ex]
            if (v5 > iso) != (v6 > iso):
                if yt[ey + 1] < 0:
                    add_point(vec3(x1, y0 + cell * (iso - v5) / (v6 - v5), z))
                    yt[ey + 1] = next_point
                    next_point += 1
                edge[5] = yt[ey + 1]
            if (v7 > iso) != (v6 > iso):
                if xt[ex + res] < 0:
                    add_point(vec3(x0 + cell * (iso - v7) / (v6 - v7), y1, z))
                    xt[ex + res] = next_point
                    next_point += 1
                edge[6] = xt[ex + res]
            if (v4 > iso) != (v7 > iso):
                if yt[ey] < 0:
                    add_point(vec3(x0, y0 + cell * (iso - v4) / (v7 - v4), z))
                    yt[ey] = next_point
                    next_point += 1
                edge[7] = yt[ey]
            # Verticals: edges 8-11, at corners 0, 1, 2, 3.
            if (v0 > iso) != (v4 > iso):
                if ze[a] < 0:
                    add_point(vec3(x0, y0, z0 + cell * (iso - v0) / (v4 - v0)))
                    ze[a] = next_point
                    next_point += 1
                edge[8] = ze[a]
            if (v1 > iso) != (v5 > iso):
                if ze[a + 1] < 0:
                    add_point(vec3(x1, y0, z0 + cell * (iso - v1) / (v5 - v1)))
                    ze[a + 1] = next_point
                    next_point += 1
                edge[9] = ze[a + 1]
            if (v2 > iso) != (v6 > iso):
                if ze[a + S + 1] < 0:
                    add_point(vec3(x1, y1, z0 + cell * (iso - v2) / (v6 - v2)))
                    ze[a + S + 1] = next_point
                    next_point += 1
                edge[10] = ze[a + S + 1]
            if (v3 > iso) != (v7 > iso):
                if ze[a + S] < 0:
                    add_point(vec3(x0, y1, z0 + cell * (iso - v3) / (v7 - v3)))
                    ze[a + S] = next_point
                    next_point += 1
                edge[11] = ze[a + S]

            t = case * 16
            while TRI[t] >= 0:
                add_face((edge[TRI[t]], edge[TRI[t + 2]], edge[TRI[t + 1]]))
                t += 3
    # The top layer becomes the bottom of the next row of cubes.
    fb = ft
    xb = xt
    yb = yt
