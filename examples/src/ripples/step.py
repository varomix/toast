# Ripple pool, one step (Run Over: Points, in a Repeat Zone in the Simulation Zone).
# The water is a grid; each point's height is @position.z and its vertical speed @speed.
# Wave equation: each point accelerates toward the average height of its 4 neighbors.
# Balls (Input 1) push the water down where they sit in it, so moving balls make waves.
h = @position.z
total = 0.0
n = 0
for q in point_neighbors(0, @index, 4):
    other: vec3 = point_attr(0, "position", q)
    total += other.z
    n += 1
speed = @speed
if n > 0:
    speed += (total / n - h) * param("stiffness", 0.6)
speed *= param("damping", 0.998)
h += speed

# A ball's underside, straight below this point: ray from under the pool up into Input 1.
hit = ray_cast(1, vec3(@position.x, @position.y, -10.0), (0, 0, 1), 20.0)
if hit.hit and hit.position.z < h:
    # Displaced water: the surface can't be above the ball's underside here. It moves with the
    # ball's surface, and that motion spreads outward as a wave once the ball moves on.
    speed = (hit.position.z - h) * param("splash", 0.5)
    h = hit.position.z

@speed: float = speed
@position.z = h
