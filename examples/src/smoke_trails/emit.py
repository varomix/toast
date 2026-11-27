# Smoke trails, make room (Run Over: Points): the comets and the smoke's volume are one geometry
# here. Each comet switches on the voxels along its path since the last frame: voxel_at() finds
# the voxel at a position, activate_voxel() adds it and the ones around it to every grid.
@prev: vec3
for s in range(9):
    p = lerp(@prev, @position, s / 8.0)
    activate_voxel(voxel_at(0, "density", p), param("room", 3))
