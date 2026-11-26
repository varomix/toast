# Tree (Run Over: Geometry): grows a whole tree from nothing, using lists as a stack.
# Each branch is a few bent segments; at its end it splits into children, which are pushed on
# the stack until the depth runs out. With "growth" below 0 (the default), the tree grows with
# the timeline: one level of branches every 20 frames.
from toast_lib.tree import child_rotation, bend_up, grown

depth_max = param("depth", 7)
children = param("children", 3)
trunk_length = param("trunk_length", 1.4)
ratio = param("length_ratio", 0.72)
spread = param("spread", 0.7)
reach_up = param("reach_up", 0.12)
seed = param("seed", 0)
growth = param("growth", -1.0)
if growth < 0:
    growth = @frame / 20.0
segments = 4
# Points added in this run are numbered from point_count(0) on, in the order they are added:
# keep that number to connect and color them later (lists can't hold add_point() results).
next_point = point_count(0)

# The stack: one entry per branch still to grow.
s_point = [0] * 512                    # the point the branch starts at
s_pos: list[vec3] = [(0.0, 0.0, 0.0)] * 512
s_rot: list[quat] = [quat()] * 512
s_len = [0.0] * 512                    # full length of the branch
s_radius = [0.0] * 512
s_depth = [0] * 512
s_id = [0] * 512                       # the branch's number, for random()

add_point((0, 0, 0))
root = next_point
next_point += 1
set_point_attr(root, "radius", 0.1 * grown(growth, 0))
s_point[0] = root
s_len[0] = trunk_length
s_radius[0] = 0.1
s_id[0] = seed * 7919 % 1000003
top = 1

while top > 0:
    top -= 1
    prev = s_point[top]
    pos = s_pos[top]
    q = s_rot[top]
    full = s_len[top]
    radius = s_radius[top]
    depth = s_depth[top]
    bid = s_id[top]
    g = grown(growth, depth)
    if g <= 0:
        continue
    seg_len = full * g / segments
    for k in range(segments):
        # Wobble a little, and reach for the light.
        wobble = quat_euler((signed_noise(bid * 1.7 + k) * 0.25, signed_noise(bid * 3.1 + k) * 0.25, 0))
        q = bend_up(q * wobble, reach_up)
        pos = pos + rotate(q, (0, 0, seg_len))
        add_point(pos)
        pt = next_point
        next_point += 1
        add_edge(prev, pt)
        set_point_attr(pt, "radius", radius * g * lerp(1.0, ratio * 0.9, (k + 1) / segments))
        prev = pt
    if depth + 1 >= depth_max or g < 1:
        set_point_attr(prev, "leaf", True)
        set_point_attr(prev, "leaf_id", bid)   # leaves.py turns each leaf by it
        continue
    for c in range(children):
        if top >= 512:
            break
        # A child's number comes from its parent's, never from how many branches came before:
        # a branch keeps its shape when new ones start growing elsewhere in the tree.
        cid = (bid * 61 + c + 1) % 1000003
        s_point[top] = prev
        s_pos[top] = pos
        s_rot[top] = child_rotation(q, c, spread, cid)
        s_len[top] = full * ratio * (0.8 + 0.4 * random(cid, 5))
        s_radius[top] = radius * ratio * 0.9
        s_depth[top] = depth + 1
        s_id[top] = cid
        top += 1
