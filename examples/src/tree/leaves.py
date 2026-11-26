# Tree, step 2 (Run Over: Instances): turn and size each leaf at random.
spin = quat_euler((random(@index, 1) * 1.2 - 0.6, random(@index, 2) * 1.2 - 0.6, random(@index, 3) * math.tau))
s = param("leaf_size", 0.18) * (0.6 + 0.8 * random(@index, 4))
@transform = mat4_compose(@position, spin, s)
