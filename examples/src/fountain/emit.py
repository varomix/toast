# Fountain, emit (Run Over: Geometry, in the Simulation Zone): `rate` new particles per frame,
# born at random places on the emitter's surface (Input 1), area weighted, with
# random_surface_point(). Each starts along the surface normal. The same frame always emits the
# same particles: their ids come from the frame number.
rate = param("rate", 250, min=0, max=100000)
speed = param("speed", 3.2)
spread = param("spread", 0.5)
seed = param("seed", 0)
frame = int(@frame)
first = frame * rate
for k in range(rate):
    pid = first + k
    h = random_surface_point(1, pid, seed)
    if not h.hit:
        break
    p = add_point(h.position + h.normal * 0.01)
    jitter = vec3(random(pid, seed + 7), random(pid, seed + 8), random(pid, seed + 9)) * 2.0 - 1.0
    set_point_attr(p, "velocity", (h.normal + jitter * spread) * speed * (0.6 + 0.4 * random(pid, seed + 10)))
    set_point_attr(p, "age", 0.0)
    set_point_attr(p, "id", pid)
@velocity: vec3
@age: float
@id: int
