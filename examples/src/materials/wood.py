# Wood (Run Over: Shader): growth rings around a trunk lying along the object's x axis, warped by noise like a real
# trunk, with dark late wood, fine grain along the rings and small pores.
scale = param("scale", 1.0)
rings = param("rings", 11.0)
light = param("light", (0.62, 0.38, 0.19, 1.0))
dark = param("dark", (0.24, 0.11, 0.045, 1.0))

p = (@generated - 0.5) * 2.0 * scale
# The trunk's center is off the object's, so the rings curve across its faces.
warp = fbm(p * vec3(0.25, 1.2, 1.2), 4.0) - 0.5
r = length(vec2(p.y + 0.7, p.z - 0.5)) * rings + warp * 2.0
ring = frac(r)
late = smoothstep(0.55, 0.9, ring) * (1.0 - smoothstep(0.95, 1.0, ring))
# Grain: noise stretched along the trunk.
grain = fbm(vec3(p.x * 1.5, p.y * 30.0, p.z * 30.0), 3.0)
pores = smoothstep(0.72, 0.8, noise(vec3(p.x * 6.0, p.y * 90.0, p.z * 90.0)))

t = clamp(late * 0.75 + (grain - 0.5) * 0.5 + pores * 0.3, 0.0, 1.0)
c = lerp(light.xyz, dark.xyz, t) * lerp(0.85, 1.1, fbm(p * 0.8 + 4.0, 2.0))
output("color", vec4(c.x, c.y, c.z, 1.0))
output("roughness", lerp(0.45, 0.7, late + pores))
output("height", grain * 0.3 - late * 0.15 - pores * 0.4)
