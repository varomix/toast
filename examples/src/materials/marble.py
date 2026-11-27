# Marble (Run Over: Shader): veins where a sine wave crosses zero, bent by turbulence, over a
# cloudy white base, with thinner veins across them.
scale = param("scale", 1.0)
vein_color = param("vein", (0.05, 0.07, 0.065, 1.0))
base_color = param("base", (0.9, 0.88, 0.84, 1.0))

p = @generated * 2.0 * scale
t = p.x * 2.5 + p.z * 1.2 + (fbm(p * 1.6, 6.0) - 0.5) * 7.0
s = abs(sin(t * math.pi))
vein = 1.0 - smoothstep(0.0, 0.08, s)
# A soft halo where the vein bled into the stone.
halo = 1.0 - smoothstep(0.0, 0.45, s)
t2 = p.y * 4.0 - p.x * 2.0 + (fbm(p * 3.5 + 7.0, 5.0) - 0.5) * 6.0
fine = 1.0 - smoothstep(0.0, 0.04, abs(sin(t2 * math.pi)))
cloud = fbm(p * 2.5 + 3.0, 4.0)

base = lerp(base_color.xyz, base_color.xyz * vec3(0.92, 0.9, 0.85), cloud)
c = lerp(base, vein_color.xyz, clamp(vein * 0.95 + halo * 0.18 + fine * 0.5, 0.0, 1.0))
output("color", vec4(c.x, c.y, c.z, 1.0))
output("roughness", 0.06 + vein * 0.12)
