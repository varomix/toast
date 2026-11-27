# Lava, flow (Run Over: Points): one step of lava running downhill. Each point trades lava with
# its four neighbors, in proportion to the difference of their surfaces (ground + lava) and to
# how hot both are: molten lava runs, cooled lava stops. Heat moves with the lava, and thin
# lava cools fastest. A vent at the top pours fresh lava, in pulses.
vent = param("vent", (0.0, 3.2, 0.0))
radius = param("radius", 0.35)
rate = param("rate", 0.0015)
k = param("flow", 0.22)
cooling = param("cooling", 0.00003)

ground = @ground
lava = @lava
heat = @heat
surface = ground + lava
new_lava = lava
warmth = lava * heat
for q in point_neighbors(0, @index, 4):
    other_lava = point_attr(0, "lava", q)
    other_heat = point_attr(0, "heat", q)
    drop = point_attr(0, "ground", q) + other_lava - surface
    # The hotter of the two decides, so molten lava also runs onto dry ground.
    mobility = pow(max(heat, other_heat), 2.0)
    f = k * mobility * drop
    # Never more than a quarter of what the giver has (each point has four neighbors), so the
    # lava doesn't go below zero; both points compute the same amount, so none is lost.
    if f > 0.0:
        f = min(f, other_lava * 0.25)
        warmth += f * other_heat
    else:
        f = max(f, -lava * 0.25)
        warmth += f * heat
    new_lava += f

d = length(vec2(@position.x - vent.x, @position.y - vent.y))
if d < radius:
    pulse = 0.4 + 0.6 * noise(@time * 0.6)
    add = rate * pulse * (1.0 - d / radius)
    new_lava += add
    warmth += add

new_heat = 0.0
if new_lava > 0.000001:
    new_heat = warmth / new_lava - cooling / (new_lava + 0.04)
@lava = new_lava
@heat = clamp(new_heat, 0.0, 1.0)
@position.z = ground + new_lava
