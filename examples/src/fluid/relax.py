# Fluid, step 4 of 4 (Run Over: Points): push crowded particles apart (double density
# relaxation), keep them in the tank and out of the obstacle (the mesh on Input 1), and derive
# the velocity from how far they moved.
h = param("radius", 0.1)
dt = param("delta_time", 0.008)
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
# The mirrored neighbors behind the walls, the floor and the obstacle (see density.py) push
# the particle away from them.
def mirror_push(d, away: vec3, h, pr, npr, dt):
    t = max(1 - 2 * d / h, 0.0)
    return away * (dt * dt * (pr * t + npr * t * t) * 0.5)


size = param("tank", (1.2, 0.45, 3.0))       # same as in density.py
pr0 = @pressure
npr0 = @near_pressure
move += mirror_push(p.z, vec3(0, 0, 1), h, pr0, npr0, dt)
move += mirror_push(size.x - p.x, vec3(-1, 0, 0), h, pr0, npr0, dt)
move += mirror_push(p.x + size.x, vec3(1, 0, 0), h, pr0, npr0, dt)
move += mirror_push(size.y - p.y, vec3(0, -1, 0), h, pr0, npr0, dt)
move += mirror_push(p.y + size.y, vec3(0, 1, 0), h, pr0, npr0, dt)
c = closest_point(1, p)
if c.hit and c.distance > 0:
    move += mirror_push(c.distance, (p - c.position) / c.distance, h, pr0, npr0, dt)

# Never more than a fifth of the radius per substep: keeps it stable when it gets crowded.
if length(move) > h * 0.2:
    move = normalize(move) * h * 0.2
p += move

# The tank.
p.x = clamp(p.x, -size.x, size.x)
p.y = clamp(p.y, -size.y, size.y)
p.z = clamp(p.z, 0.0, size.z)

# Obstacle (the mesh on Input 1). A particle never crosses its surface: if the move from where
# it was (outside) to p goes through a face, it stops on the side it came from and only slides
# along the face. This works for open meshes too, and doesn't guess the side from a normal.
margin = param("obstacle_margin", 0.02)
step = p - @previous
travel = length(step)
if travel > 0:
    hit = ray_cast(1, @previous, step, travel + margin)
    if hit.hit:
        n = hit.normal
        if dot(@previous - hit.position, n) < 0:
            n = -n                          # the face's side the particle came from
        stop = hit.position + n * margin
        rest = p - hit.position
        slide = rest - n * dot(rest, n)
        # Sliding mustn't cross another face either (in a crease): then it just stops.
        if length(slide) > 0 and ray_cast(1, stop, slide, length(slide) + margin).hit:
            slide = vec3(0, 0, 0)
        p = stop + slide
# Keep a thin gap to the surface, pushing away from the closest point (always outward, since
# the particle is on the outside).
c = closest_point(1, p)
if c.hit and c.distance < margin and c.distance > 0:
    p = c.position + (p - c.position) / c.distance * margin

# The tank again, in case the obstacle pushed a particle out of it.
p.x = clamp(p.x, -size.x, size.x)
p.y = clamp(p.y, -size.y, size.y)
p.z = clamp(p.z, 0.0, size.z)
# Last check: if the whole move still crosses a face (pushed in a crease or against the tank),
# the particle stops just before it. Everything before the first hit is outside.
step = p - @previous
travel = length(step)
if travel > 0:
    last = ray_cast(1, @previous, step, travel)
    if last.hit:
        p = @previous + step / travel * max(last.distance - margin * 0.5, 0.0)

v = (p - @previous) / dt
# Viscosity (XSPH): lean toward the neighbors' average velocity.
if weight > 0:
    v = lerp(v, blur / weight, param("viscosity", 0.1))
@velocity = v
@position = p
@speed: float = length(v)
