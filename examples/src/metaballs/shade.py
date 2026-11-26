# Metaballs, color (Run Over: Points): each surface point blends the colors of the balls by how
# strongly each one pulls on it, so where two balls merge their colors run together.
from toast_lib.metaballs import ball, ball_color

count = clamp(param("balls", 8, min=1, max=16), 1, 16)
seed = param("seed", 0)
spread = param("spread", 1.3)
speed = param("speed", 1.0)
total = vec3(0, 0, 0)
weight = 0.0
for b in range(count):
    c = ball(b, @time * speed, seed, spread)
    d = @position - c.xyz
    w = pow(c.w * c.w / max(dot(d, d), 1e-6), 3.0)   # sharpened so each ball keeps its color
    total += ball_color(b, seed) * w
    weight += w
@color = total / max(weight, 1e-9)
