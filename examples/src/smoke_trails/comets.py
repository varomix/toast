# Smoke trails, comets (Run Over: Points): each point flies its own loop through the air, set by
# the time, so scrubbing works. @prev is where it was a frame ago, for the trail between.
speed = param("speed", 0.7)
dt = param("delta_time", 0.0417)


def path(k, t):
    a = t * (0.9 + 0.17 * k) + k * 2.1
    r = 1.5 + 0.45 * sin(t * 0.7 + k)
    return vec3(cos(a) * r, sin(a) * r * 0.8, 1.7 + 0.8 * sin(t * 1.3 + k * 1.7))


k = float(@index)
t = @time * speed
@prev: vec3 = path(k, t - dt * speed)
@position = path(k, t)
