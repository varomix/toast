# Glazed tiles (Run Over: Shader): Truchet tiles, two quarter circles turned at random, which
# join into a maze of bands; glossy glaze, rough grout between the tiles.
from toast_lib.tiling import box_uv

scale = param("scale", 5.0)
glaze = param("glaze", (0.02, 0.12, 0.42, 1.0))
band = param("band", (0.92, 0.9, 0.82, 1.0))

uv = box_uv(@object, @normal) * scale
cell = floor(uv)
f = uv - cell
if hash01(cell) < 0.5:
    f = vec2(1.0 - f.x, f.y)
# Distance to the nearer of the two arcs (around opposite corners, radius 0.5).
d = min(abs(length(f) - 0.5), abs(length(f - 1.0) - 0.5))
stripe = 1.0 - smoothstep(0.1, 0.12, d)
edge = min(min(f.x, 1.0 - f.x), min(f.y, 1.0 - f.y))
grout = 1.0 - smoothstep(0.015, 0.03, edge)
# The glaze pools a little darker at the tile's edges.
pool = smoothstep(0.03, 0.2, edge)

c = lerp(glaze.xyz * lerp(0.6, 1.0, pool), band.xyz, stripe)
c = lerp(c, vec3(0.45, 0.43, 0.4), grout)
output("color", vec4(c.x, c.y, c.z, 1.0))
output("roughness", lerp(0.08, 0.9, grout))
output("height", 1.0 - grout + stripe * 0.08 + pool * 0.1)
