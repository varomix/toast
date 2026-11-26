# Sketch, fringe (Run Over: Geometry): on a Grease Pencil object this runs once per layer, on
# that layer's strokes. Along every stroke, every few points, it draws a short hair stroke out to
# the side with add_point() + add_curve(): the new strokes go into the same layer.
every = param("every", 3, min=1)
hair = param("hair", 0.2)
side_axis = param("view_axis", (0.0, 1.0, 0.0))   # strokes lie across this axis (the camera's)
for c in range(curve_count(0)):
    k = 0
    before = vec3(0, 0, 0)
    for p in curve_points(0, c, 4096):
        here: vec3 = point_attr(0, "position", p)
        if k > 0 and k % every == 0:
            t = normalize(here - before)
            side = normalize(cross(t, side_axis))
            size = hair * (0.3 + noise(here * 3.0 + 7.0))
            tip = here + side * size + t * size * 0.4
            add_curve((add_point(here), add_point(lerp(here, tip, 0.5) + side * size * 0.1), add_point(tip)))
        before = here
        k += 1
