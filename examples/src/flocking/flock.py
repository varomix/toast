# Flocking, step 2 (Run Over: Points, inside the Simulation Zone).
# Classic boids: every boid looks at its neighbors (nearby_points) and steers to
#   - separate: not crowd them,
#   - align: fly the same way,
#   - cohere: stay with the group,
# plus a slow curl-noise "wind" so the flock keeps changing, and a soft ball it stays inside.
# Neighbors are read as they were at the start of the step, so the result is the same on any
# number of threads.
view = param("view_radius", 0.7)
personal = param("personal_space", 0.25)
min_speed = param("min_speed", 0.8)
max_speed = param("max_speed", 2.5)
bounds = param("bounds", 5.0)
dt = param("delta_time", 0.04)

p = @position
v = @velocity
center = vec3(0, 0, 0)
heading = vec3(0, 0, 0)
push = vec3(0, 0, 0)
n = 0
for j in nearby_points(0, p, view, 20):
    if j == @index:
        continue
    q: vec3 = point_attr(0, "position", j)
    w: vec3 = point_attr(0, "velocity", j)
    center += q
    heading += w
    n += 1
    away = p - q
    dist = length(away)
    if 0 < dist < personal:
        push += away / (dist * dist)

steer = push * param("separation", 0.6)
if n > 0:
    steer += (center / n - p) * param("cohesion", 0.8)
    steer += (heading / n - v) * param("alignment", 1.2)

# Stay inside the ball, softly.
r = length(p)
if r > bounds:
    steer -= p / r * (r - bounds) * 4.0
steer += curl_noise(p * 0.25 + (0, 0, @time * 0.15)) * param("wander", 1.0)

v += steer * dt
speed = length(v)
if speed > 0:
    v = v / speed * clamp(speed, min_speed, max_speed)
@velocity = v
@position = p + v * dt
