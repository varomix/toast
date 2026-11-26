# Reaction-diffusion, step 3 (Run Over: Points): raise the surface where B is and color it.
b = smoothstep(0.1, 0.4, @b)
@position += @normal * b * param("height", 0.04)
low = param("color_a", (0.02, 0.03, 0.08))
high = param("color_b", (1.0, 0.55, 0.15))
@color = lerp(low, high, b)
