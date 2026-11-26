# Differential growth, step 2 (Run Over: Points): color along the loop and lift it into a ribbon.
t = float(@index) / max(@count, 1)
@color = lerp(param("color_a", (0.1, 0.8, 0.6)), param("color_b", (0.9, 0.2, 0.5)), 0.5 + 0.5 * sin(t * math.tau * 3))
