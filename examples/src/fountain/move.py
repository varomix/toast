# Fountain, move (Run Over: Points, in the Simulation Zone): gravity and air drag, a bounce on the
# floor (z = 0) that loses energy, and death of old age (remove_point).
dt = param("delta_time", 0.0417)   # the Simulation Zone's Delta Time
life = param("life", 3.0) * (0.7 + 0.6 * random(@id, 11))
@age += dt
if @age > life:
    remove_point(@index)
    return
v = @velocity
v.z -= param("gravity", 9.8) * dt
v *= 1.0 - param("drag", 0.4) * dt
p = @position + v * dt
if p.z < 0.0:
    p.z = -p.z * param("bounce", 0.4)
    v.z = -v.z * param("bounce", 0.4)
    v.x *= 0.8
    v.y *= 0.8
@position = p
@velocity = v
@life_left: float = 1.0 - @age / life
