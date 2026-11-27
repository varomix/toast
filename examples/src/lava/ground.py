# Lava, ground (Run Over: Points): a hillside sloping down towards the camera, with gullies for
# the lava to find. Starts the simulation with no lava.
slope = param("slope", 0.25)
p = @position
gullies = abs(signed_noise(vec3(p.x * 0.35, p.y * 0.12, 0.5)))
@ground = p.y * slope + (fbm(p * 0.4, 4.0) - 0.5) * 0.9 + gullies * 0.25
@position.z = @ground
@lava = 0.0
@heat = 0.0
