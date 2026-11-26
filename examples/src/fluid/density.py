# Fluid, step 3 of 4 (Run Over: Points): how crowded each particle is, and its pressure.
h = param("radius", 0.1)
p = @position
density = 0.0
near = 0.0
for j in nearby_points(0, p, h, 40):
    if j == @index:
        continue
    q: vec3 = point_attr(0, "position", j)
    t = 1 - distance(p, q) / h
    density += t * t
    near += t * t * t


# The tank walls, the floor and the obstacle count as fluid: each acts as a mirror, and a
# particle near one has its reflection as a neighbor (relax.py pushes it away from it). Without
# this, a particle on the floor only has neighbors above it, nothing ever lifts it, and the
# bottom layer gets crushed into a sheet that never settles.
def mirror(d, h):
    t = max(1 - 2 * d / h, 0.0)
    return vec2(t * t, t * t * t)


size = param("tank", (1.2, 0.45, 3.0))       # same as in relax.py
g = mirror(p.z, h) + mirror(size.x - p.x, h) + mirror(p.x + size.x, h)
g += mirror(size.y - p.y, h) + mirror(p.y + size.y, h)
c = closest_point(1, p)
if c.hit:
    g += mirror(c.distance, h)
density += g.x
near += g.y
@pressure: float = param("stiffness", 20.0) * (density - param("rest_density", 3.0))
@near_pressure: float = param("near_stiffness", 80.0) * near
