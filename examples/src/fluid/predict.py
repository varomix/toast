# Fluid, step 2 of 4 (Run Over: Points): apply gravity and move ahead (Clavet et al. 2005,
# "Particle-based viscoelastic fluid simulation"). Remembers where each particle was.
# 6 substeps of 0.008 s per frame (the Repeat Zone). Fewer, longer steps make the relaxation
# overshoot: the fluid jitters and never settles.
dt = param("delta_time", 0.008)
@previous: vec3 = @position
@velocity += param("gravity", (0.0, 0.0, -9.8)) * dt
@position += @velocity * dt
