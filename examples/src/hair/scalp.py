# Hair, step 0 (Run Over: Faces): which faces grow hair. output() makes a Boolean socket on the
# node, used as the Selection of Distribute Points on Faces: the top and back of the head.
up = @normal.z + 0.6 * max(@normal.y, 0)
output("scalp", up > param("hairline", 0.05) + signed_noise(@position * 3) * 0.1)
