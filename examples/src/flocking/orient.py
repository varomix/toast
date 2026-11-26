# Flocking, step 3 (Run Over: Instances): point each boid's instance where it flies.
# Instance on Points copies the points' attributes to the instances, so @velocity is here.
v = @velocity
speed = length(v)
facing = quat_between((0, 0, 1), v / speed) if speed > 0 else quat()
# Bank into turns a little: roll around the flight direction by the sideways velocity.
roll = quat_axis_angle((0, 0, 1), clamp(v.x * 0.15, -0.6, 0.6))
s = param("size", 0.1) * (0.8 + 0.4 * random(@index, 7))
@transform = mat4_compose(@position, facing * roll, s)
# 0 when slow, 1 when fast: the material colors the cones with it.
@fast: float = smoothstep(0.8, 2.5, speed)
