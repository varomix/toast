# Fluid, step 4 of 4 (Run Over: Points): push crowded particles apart (double density
# relaxation), keep them in the tank and out of the obstacle (the mesh on Input 1), and derive
# the velocity from how far they moved.
h = param("radius", 0.1)
dt = param("delta_time", 0.016)
@previous: vec3                    # written by predict.py; say its type, or it reads as a float
p = @position
move = vec3(0, 0, 0)
blur = vec3(0, 0, 0)
weight = 0.0
for j in nearby_points(0, p, h, 40):
    if j == @index:
        continue
    q: vec3 = point_attr(0, "position", j)
    d = q - p
    r = length(d)
    if r <= 0:
        continue
    t = 1 - r / h
    pr: float = point_attr(0, "pressure", j)
    npr: float = point_attr(0, "near_pressure", j)
    push = dt * dt * (0.5 * (@pressure + pr) * t + 0.5 * (@near_pressure + npr) * t * t)
    move -= d / r * push * 0.5           # each particle of a pair takes half
    w: vec3 = point_attr(0, "velocity", j)
    blur += w * t
    weight += t
# Never more than a fifth of the radius per substep: keeps it stable when it gets crowded.
if length(move) > h * 0.2:
    move = normalize(move) * h * 0.2
p += move

# Obstacle: particles that went just inside the mesh on Input 1 go back to its surface.
c = closest_point(1, p)
if c.hit and c.distance < h and dot(p - c.position, c.normal) < 0:
    p = c.position + c.normal * 0.005

# The tank.
size = param("tank", (1.2, 0.45, 3.0))
p.x = clamp(p.x, -size.x, size.x)
p.y = clamp(p.y, -size.y, size.y)
p.z = clamp(p.z, 0.0, size.z)

v = (p - @previous) / dt
# Viscosity (XSPH): lean toward the neighbors' average velocity.
if weight > 0:
    v = lerp(v, blur / weight, param("viscosity", 0.1))
@velocity = v
@position = p
@speed: float = length(v)
