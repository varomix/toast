# Smoke, projection (Run Over: Voxels): take the pressure's gradient off the velocity. What is
# left flows without bunching up: the swirls of real smoke.
@velocity = @velocity - grid_gradient(0, "pressure", @position)
