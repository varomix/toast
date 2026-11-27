# A procedural texture for the shader editor's Toast node (EEVEE): cells, wood rings and wear.
# Run Over: Shader
scale = param("scale", 4.0)
rings = param("rings", 12.0)
tint = param("tint", (0.8, 0.5, 0.3, 1.0))

p = @generated * scale
cell = voronoi(p, 0.9)
# Rings around each cell's center, warped by noise.
r = frac(cell.distance * rings + fbm(p * 2.0, 3.0) * 0.5)
grain = smoothstep(0.0, 0.15, r) * smoothstep(1.0, 0.6, r)
c = lerp(vec3(tint.x, tint.y, tint.z) * 0.4, vec3(tint.x, tint.y, tint.z), grain)
c *= lerp(0.8, 1.1, cell.color.x)

output("color", vec4(c.x, c.y, c.z, 1.0))
output("height", grain)
output("roughness", lerp(0.35, 0.7, 1.0 - grain))
