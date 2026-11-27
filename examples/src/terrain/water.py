# Terrain, water (Run Over: Shader): waves made of a few moving noises, for Bump; deeper blue
# far out, a lighter green near the shore (the water plane's own position).
speed = param("speed", 0.3)
p = @position
t = @time * speed
w = fbm(vec3(p.x * 3.0 + t, p.y * 3.0 - t * 0.6, t), 4.0) * 0.7 + noise(vec3(p.x * 14.0 - t * 3.0, p.y * 14.0, t * 2.0)) * 0.3
far = smoothstep(4.0, 9.0, length(vec2(p.x, p.y)))
c = lerp(vec3(0.02, 0.12, 0.12), vec3(0.005, 0.03, 0.07), far)
output("color", vec4(c.x, c.y, c.z, 1.0))
output("height", w)
