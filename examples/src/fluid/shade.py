# Fluid, step 5 (Run Over: Points): color by speed, foam where it's fast.
s = smoothstep(0.0, param("fast", 3.0), @speed)
@color = lerp(param("deep", (0.02, 0.12, 0.45)), param("foam", (0.85, 0.95, 1.0)), s)
