# Ripple pool, shading (Run Over: Points): deep blue where the water is calm, light where it
# is steep (crests and the bow wave in front of each ball), white foam where it moves fast.
slope = 0.0
for q in point_neighbors(0, @index, 4):
    other: vec3 = point_attr(0, "position", q)
    slope = max(slope, abs(other.z - @position.z))
steep = smoothstep(0.0, param("steep", 0.02), slope)
foam = smoothstep(param("foam_start", 0.01), param("foam_end", 0.04), abs(@speed))
deep = param("deep", (0.01, 0.06, 0.12))
light_water = param("light", (0.1, 0.45, 0.55))
@color = lerp(lerp(deep, light_water, steep), (0.9, 0.95, 1.0), foam)
