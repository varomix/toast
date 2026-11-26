# Fluid, step 3 of 4 (Run Over: Points): how crowded each particle is, and its pressure.
h = param("radius", 0.1)
density = 0.0
near = 0.0
for j in nearby_points(0, @position, h, 40):
    if j == @index:
        continue
    q: vec3 = point_attr(0, "position", j)
    t = 1 - distance(@position, q) / h
    density += t * t
    near += t * t * t
@pressure: float = param("stiffness", 20.0) * (density - param("rest_density", 3.0))
@near_pressure: float = param("near_stiffness", 80.0) * near
