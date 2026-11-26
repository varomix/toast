# Reaction-diffusion, step 2 (Run Over: Points, inside a Repeat Zone in the Simulation Zone).
# Gray-Scott: two chemicals spread over the surface (diffusion: each point moves toward the
# average of its neighbors) and react (A + 2B -> 3B, A is fed in, B is killed off).
# Feed and kill change with height, so one sphere shows spots, stripes and mazes at once.
a = @a
b = @b
sum_a = 0.0
sum_b = 0.0
n = 0
for q in point_neighbors(0, @index, 12):
    sum_a += point_attr(0, "a", q)
    sum_b += point_attr(0, "b", q)
    n += 1
if n == 0:
    return
lap_a = sum_a / n - a
lap_b = sum_b / n - b

t = clamp(@position.z * 0.5 + 0.5, 0, 1)        # 0 at the bottom, 1 at the top
feed = lerp(param("feed_bottom", 0.030), param("feed_top", 0.055), t)
kill = lerp(param("kill_bottom", 0.057), param("kill_top", 0.062), t)
reaction = a * b * b
dt = param("delta_time", 1.0)
@a = clamp(a + (param("diffuse_a", 1.0) * lap_a - reaction + feed * (1 - a)) * dt, 0, 1)
@b = clamp(b + (param("diffuse_b", 0.5) * lap_b + reaction - (kill + feed) * b) * dt, 0, 1)
