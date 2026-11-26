# Differential growth (Run Over: Geometry, inside the Simulation Zone).
# The input is one closed loop of points joined by edges, in order. Every step, each point
#   - is pulled toward the middle of its two neighbors (keeps the line smooth),
#   - is pushed away from every other point nearby (makes it buckle and fold),
# and edges that got too long are split by a new point. The whole loop is rebuilt: new points
# and edges are added, then the old points are removed.
# Run Over Geometry runs once, on one core: this is a test of how far one sequential kernel goes.
n = point_count(0)
repel_radius = param("repel_radius", 0.08)
split = param("split_length", 0.035)
max_points = param("max_points", 12000)
attraction = param("attraction", 0.5)
repulsion = param("repulsion", 0.01)

base = n
added = 0
first = vec3(0, 0, 0)
last = vec3(0, 0, 0)
can_split = n < max_points
for i in range(n):
    p: vec3 = point_attr(0, "position", i)
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
    # Points grow at different speeds (slow noise), so the shape isn't symmetric.
    rate = 0.5 + noise(p * 2.0 + @time * 0.05)
    move = ((a + b) * 0.5 - p) * attraction + push * repulsion * rate
    move.z = 0
    # Never move more than a fraction of an edge per step, or the line tangles.
    if length(move) > split * 0.2:
        move = normalize(move) * split * 0.2
    np = p + move
    if i > 0 and can_split and distance(last, np) > split:
        add_point((last + np) * 0.5)
        added += 1
    add_point(np)
    added += 1
    if i == 0:
        first = np
    last = np
if can_split and distance(last, first) > split:
    add_point((last + first) * 0.5)
    added += 1
for k in range(added):
    add_edge(base + k, base + (k + 1) % added)
for i in range(n):
    remove_point(i)
