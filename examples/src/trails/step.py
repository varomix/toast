# Trails, one frame (Run Over: Curves, in the Simulation Zone): each curve is a particle's trail.
# The particle is the curve's tip: it moves through a curl noise flow, and extend_curve() adds
# its new position as the curve's new tip. Once a trail has `trail` points, its oldest point is
# removed, so trails keep their length and slide along behind the particles.
tip = 0
root = 0
n = 0
for p in curve_points(0, @index, 4096):
    if n == 0:
        root = p
    tip = p
    n += 1
here: vec3 = point_attr(0, "position", tip)
flow = curl_noise(here * param("scale", 0.6) + (0.0, 0.0, @time * param("evolve", 0.15)))
# A pull toward the middle keeps the swarm together.
pull = -here * param("pull", 0.3) * max(length(here) - param("radius", 1.6), 0.0)
extend_curve(@index, here + (flow + pull) * param("speed", 0.04))
if n >= param("trail", 48):
    remove_point(root)
@hue: float = random(@index, param("seed", 0))
