# Crawlers, start (Run Over: Geometry): one curve of one point per crawler, at random places on
# the shape's surface (Input 1), area weighted.
for k in range(param("count", 1500)):
    h = random_surface_point(1, k, param("seed", 0))
    add_curve((add_point(h.position),))
