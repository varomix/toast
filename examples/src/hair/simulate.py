# Hair, step 2 (Run Over: Curves, inside the Simulation Zone). One curve = one strand.
# Each strand copies its points into lists, moves them (Verlet: velocity is position - previous
# position), then walks from root to tip keeping every segment its rest length ("follow the
# leader"), and pushes points out of the collider connected to Input 1 and out of the head.
# All of it runs per strand, in parallel over strands.
dt = param("delta_time", 0.04)
gravity = param("gravity", (0.0, 0.0, -9.8))
damping = param("damping", 0.97)
stiffness = param("stiffness", 0.006)      # pull toward the groomed shape (0 = limp)
wind = param("wind", 1.5)
head_radius = param("head_radius", 1.0)
margin = param("margin", 0.03)

ids = [0] * 32
pos: list[vec3] = [(0.0, 0.0, 0.0)] * 32
old: list[vec3] = [(0.0, 0.0, 0.0)] * 32
rest: list[vec3] = [(0.0, 0.0, 0.0)] * 32
n = 0
for p in curve_points(0, @index, 32):
    ids[n] = p
    n += 1

for k in range(n):
    x: vec3 = point_attr(0, "position", ids[k])
    prev: vec3 = point_attr(0, "prev", ids[k])
    r: vec3 = point_attr(0, "rest", ids[k])
    rest[k] = r
    old[k] = x
    if k == 0:
        pos[k] = r                                # the root stays on the head
        continue
    gust = curl_noise(x * 0.6 + (@time * 0.8, 0, 0)) + (1.0, 0.0, 0.0)
    a = gravity + gust * wind
    nx = x + (x - prev) * damping + a * dt * dt
    pos[k] = lerp(nx, r, stiffness)

for k in range(1, n):
    seg = length(rest[k] - rest[k - 1])
    # Collide with the head (a ball at the origin) and with the mesh on Input 1.
    if length(pos[k]) < head_radius + margin:
        pos[k] = normalize(pos[k]) * (head_radius + margin)
    c = closest_point(1, pos[k])
    if c.hit and dot(pos[k] - c.position, c.normal) < margin:
        pos[k] = c.position + c.normal * margin
    # Follow the leader: keep the segment length.
    d = pos[k] - pos[k - 1]
    pos[k] = pos[k - 1] + normalize(d) * seg

for k in range(n):
    set_point_attr(ids[k], "position", pos[k])
    set_point_attr(ids[k], "prev", old[k])
