# Reaction-diffusion, step 1 (Run Over: Points): chemical A everywhere, a few drops of B.
@a: float = 1.0
spots = noise(@position * param("spot_scale", 3.0) + param("seed", 0.0))
@b: float = 1.0 if spots > param("threshold", 0.68) else 0.0
