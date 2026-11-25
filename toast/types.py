# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast value types and their C++ and ABI equivalents."""

import functools
from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    name: str  # Toast name, used in messages and signatures.
    cpp: str  # C++ type in generated code.
    ncomp: int  # Float components for vectors, 1 for scalars.
    abi: int  # ToastAttr.type code, -1 if it can't be an attribute.
    zero: str  # C++ zero value, for hoisted declarations.

    @property
    def is_vec(self):
        return self.name.startswith("vec")

    @property
    def is_scalar(self):
        return self in (FLOAT, INT, BOOL)

    @property
    def is_array(self):
        return self.name.startswith("list[")

    def __str__(self):
        return self.name


FLOAT = Type("float", "float", 1, 0, "0.0f")
INT = Type("int", "int32_t", 1, 1, "0")
BOOL = Type("bool", "bool", 1, 2, "false")
VEC2 = Type("vec2", "toast::float2", 2, 3, "toast::float2(0.0f)")
VEC3 = Type("vec3", "toast::float3", 3, 4, "toast::float3(0.0f)")
VEC4 = Type("vec4", "toast::float4", 4, 5, "toast::float4(0.0f)")
# Rotations and transforms, Blender's Quaternion and float4x4. Default: identity.
QUAT = Type("quat", "toast::quat", 4, 6, "toast::quat()")
MAT4 = Type("mat4", "toast::float4x4", 16, 7, "toast::float4x4()")
# Result of add_point(): a point index that only exists after the run. Opaque.
POINTREF = Type("pointref", "int64_t", 1, -1, "0")
# Result of ray_cast() and closest_point(): a record with read-only fields.
HIT = Type("hit", "toast::Hit", 0, -1, "toast::Hit{}")
HIT_FIELDS = {"hit": BOOL, "position": VEC3, "normal": VEC3, "distance": FLOAT, "face": INT}
# Result of voronoi(): the nearest cell.
VORONOI = Type("voronoi_cell", "toast::Voronoi", 0, -1, "toast::Voronoi{}")
VORONOI_FIELDS = {"distance": FLOAT, "color": VEC3, "position": VEC3}
RECORDS = {HIT: HIT_FIELDS, VORONOI: VORONOI_FIELDS}
# Read-only properties of quat and mat4: name -> (type, C++ code with {} for the value).
PROPERTIES = {
    QUAT: {"w": (FLOAT, "({}).w"), "x": (FLOAT, "({}).x"), "y": (FLOAT, "({}).y"),
           "z": (FLOAT, "({}).z")},
    MAT4: {"translation": (VEC3, "toast::mat_translation({})"),
           "rotation": (QUAT, "toast::mat_rotation({})"),
           "scale": (VEC3, "toast::mat_scale({})")},
}  # fmt: skip
# Result of calls that return nothing.
NONE = Type("none", "void", 0, -1, "")

VECS = {2: VEC2, 3: VEC3, 4: VEC4}
BY_NAME = {t.name: t for t in (FLOAT, INT, BOOL, VEC2, VEC3, VEC4, QUAT, MAT4)}
# Types an array (Toast list) can hold.
ARRAY_ELEMENTS = tuple(BY_NAME.values())
ARRAY_MAX = 4096


@functools.lru_cache(maxsize=None)
def array_type(element, size):
    """A fixed-size list of ``size`` values of ``element``."""
    return Type(f"list[{element.name}, {size}]", f"toast::Array<{element.cpp}, {size}>", 0, -1,
                f"toast::Array<{element.cpp}, {size}>{{}}")  # fmt: skip


def array_parts(t):
    """(element type, size) of an array type."""
    inner = t.name[len("list["):-1]
    name, size = inner.split(", ")
    return BY_NAME[name], int(size)

# Attributes with a known type. Anything else is a float unless declared, e.g. `@flag: bool`.
# Names are Blender's: `@color` is the active color attribute, `@normal` reads vertex, face or
# corner normals when there is no `normal` attribute.
KNOWN_ATTRS = {
    "position": VEC3,
    "normal": VEC3,
    "color": VEC3,
    "velocity": VEC3,
    "radius": FLOAT,
    "id": INT,
    # Instances: the instance's transform (Blender's instance_transform).
    "transform": MAT4,
}
