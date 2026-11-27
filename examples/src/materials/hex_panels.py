# Sci-fi panels (Run Over: Shader): a honeycomb of metal plates with grooves between them; some
# plates carry a light ring that pulses, each at its own pace (toast_lib.tiling).
from toast_lib.tiling import box_uv, hex_cell, hex_edge

scale = param("scale", 6.0)
lit = param("lit", 0.22, min=0, max=1)
light = param("light", (0.1, 0.75, 1.0, 1.0))

uv = box_uv(@object, @normal) * scale
h = hex_cell(uv)
q = vec2(h.x, h.y)
id = vec2(h.z, h.w)
e = hex_edge(q)
groove = smoothstep(0.43, 0.47, e)
r = hash01(id)
# Brushed metal, a different shade for each plate.
brushed = noise(vec2(q.x * 3.0 + r * 50.0, q.y * 80.0))
metal = vec3(0.32, 0.34, 0.37) * (0.75 + r * 0.5) + (brushed - 0.5) * 0.06
ring = (1.0 - smoothstep(0.0, 0.025, abs(e - 0.3))) * float(r < lit)
pulse = 0.5 + 0.5 * sin(@time * (1.5 + hash01(id + 3.0) * 2.0) + r * 40.0)

c = lerp(metal, vec3(0.02), groove)
output("color", vec4(c.x, c.y, c.z, 1.0))
output("metallic", 1.0 - groove)
output("roughness", lerp(0.3, 0.6, brushed) + groove * 0.3)
output("emission", vec4(light.x, light.y, light.z, 1.0))
output("strength", ring * (2.0 + pulse * 18.0))
output("height", 1.0 - groove - ring * 0.3 + smoothstep(0.3, 0.0, e) * 0.15)
