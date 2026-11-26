# Trails, start (Run Over: Geometry): one curve of one point per particle, scattered in a ball.
# add_curve() makes a curve from points made in the same run; this node runs once, before the
# Simulation Zone, on the Curves object's empty curves.
count = param("count", 1200)
radius = param("radius", 1.6)
for k in range(count):
    # A random point in the ball: a direction, and a distance that fills the volume evenly.
    d = normalize(vec3(random(k, 1), random(k, 2), random(k, 3)) * 2.0 - 1.0)
    r = radius * pow(random(k, 4), 1.0 / 3.0)
    add_curve((add_point(d * r),))
