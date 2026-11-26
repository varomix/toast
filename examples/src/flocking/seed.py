# Flocking, step 1 (Run Over: Points): start every boid at a random place, flying a random way.
radius = param("radius", 4.0)
seed = param("seed", 0)
# Random point in a ball: random direction, cube-root distance so the ball fills evenly.
d = normalize(vec3(random(@index, seed), random(@index, seed + 1), random(@index, seed + 2)) - 0.5)
r = radius * pow(random(@index, seed + 3), 1.0 / 3.0)
@position = d * r
@velocity = normalize(vec3(random(@index, seed + 4), random(@index, seed + 5),
                           random(@index, seed + 6)) - 0.5) * param("speed", 1.5)
