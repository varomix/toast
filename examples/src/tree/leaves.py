# Tree, step 2 (Run Over: Instances): turn and size each leaf at random. The random numbers come
# from the branch's number (leaf_id, set by tree.py), not @index: indices shift as the tree grows,
# and every leaf would turn at once.
@leaf_id: int
@leaf_scale: float   # 0..1, set by tree.py: leaves grow in and shrink away
lid = @leaf_id
spin = quat_euler((random(lid, 1) * 1.2 - 0.6, random(lid, 2) * 1.2 - 0.6, random(lid, 3) * math.tau))
s = param("leaf_size", 0.18) * (0.6 + 0.8 * random(lid, 4)) * @leaf_scale
@transform = mat4_compose(@position, spin, s)
