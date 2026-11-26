# Differential growth, parallel version, step 1 (Run Over: Points, inside the Simulation Zone).
# The expensive part of grow.py (each point looking at its neighbors) doesn't depend on the other
# points' results, so it runs here once per point, on every core. It only stores where each
# point goes (@next); rebuild.py then splits and reconnects the loop, which is cheap.
# Same math as grow.py: both scenes grow the same shape.
n = @count
i = @index
repel_radius = param("repel_radius", 0.08)
split = param("split_length", 0.035)
attraction = param("attraction", 0.5)
repulsion = param("repulsion", 0.01)

p = @position
a: vec3 = point_attr(0, "position", (i + n - 1) % n)
b: vec3 = point_attr(0, "position", (i + 1) % n)
push = vec3(0, 0, 0)
for j in nearby_points(0, p, repel_radius, 24):
    if j == i:
        continue
    q: vec3 = point_attr(0, "position", j)
    d = p - q
    dist = length(d)
    if dist > 0:
        push += d / dist * (1 - dist / repel_radius)
rate = 0.5 + noise(p * 2.0 + @time * 0.05)
move = ((a + b) * 0.5 - p) * attraction + push * repulsion * rate
move.z = 0
if length(move) > split * 0.2:
    move = normalize(move) * split * 0.2
@next: vec3 = p + move
