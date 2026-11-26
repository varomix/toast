# Fluid, step 2 of 4 (Run Over: Points): apply gravity and move ahead (Clavet et al. 2005,
# "Particle-based viscoelastic fluid simulation"). Remembers where each particle was.
dt = param("delta_time", 0.016)
@previous: vec3 = @position
@velocity += param("gravity", (0.0, 0.0, -9.8)) * dt
@position += @velocity * dt
