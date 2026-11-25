# Delete the faces whose normal points down.
# Run Over: Faces
if @normal.z < param("threshold", -0.5):
    remove_face(@index)
