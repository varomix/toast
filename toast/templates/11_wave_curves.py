# Make curves wave: points move up and down more toward each curve's tip.
# Run Over: Curves
amp = param("amp", 0.2)
n = 0
for p in curve_points(0, @index, 1024):
    n += 1
k = 0
for p in curve_points(0, @index, 1024):
    tip = float(k) / max(n - 1, 1)
    pos: vec3 = point_attr(0, "position", p)
    offset = signed_noise(pos * param("freq", 2.0) + (0, 0, @time)) * amp * tip
    set_point_attr(p, "position", pos + (0, 0, offset))
    k += 1
