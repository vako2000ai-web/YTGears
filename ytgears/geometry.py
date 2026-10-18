"""Procedural meshes, involute gear rims and opaque porcelain with wall thickness."""
from __future__ import annotations

import math
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
                         GeomVertexWriter, Material, NodePath, PNMImage, Texture, Vec3)

TAU = math.tau


class Mesh:
    def __init__(self, name):
        self.name, self.vertices, self.normals, self.uvs = name, [], [], []

    def triangle(self, a, b, c, uv=((0, 0), (1, 0), (1, 1)), normals=None):
        normal = (Vec3(*b) - Vec3(*a)).cross(Vec3(*c) - Vec3(*a))
        if normal.length_squared() < 1e-16: return
        normal.normalize()
        self.vertices.extend((a, b, c))
        self.normals.extend(normals or (normal, normal, normal))
        self.uvs.extend(uv)

    def quad(self, a, b, c, d, uv=((0, 0), (1, 0), (1, 1), (0, 1))):
        self.triangle(a, b, c, (uv[0], uv[1], uv[2]))
        self.triangle(a, c, d, (uv[0], uv[2], uv[3]))

    def node(self):
        data = GeomVertexData(self.name, GeomVertexFormat.get_v3n3t2(), Geom.UH_static)
        data.set_num_rows(len(self.vertices))
        vertex, normal, uv = (GeomVertexWriter(data, key) for key in ("vertex", "normal", "texcoord"))
        for v, n, t in zip(self.vertices, self.normals, self.uvs):
            vertex.add_data3(*v); normal.add_data3(*n); uv.add_data2(*t)
        triangles = GeomTriangles(Geom.UH_static)
        for i in range(0, len(self.vertices), 3): triangles.add_vertices(i, i + 1, i + 2)
        geom = Geom(data); geom.add_primitive(triangles)
        node = GeomNode(self.name); node.add_geom(geom)
        return NodePath(node)


def material(name, color, metallic=0, roughness=.4):
    mat = Material(name)
    mat.set_base_color((*color, 1))
    mat.set_metallic(metallic)
    mat.set_roughness(roughness)
    return mat


def box(name, size=(1, 1, 1)):
    x, y, z = (v / 2 for v in size)
    m = Mesh(name)
    m.quad((-x, -y, -z), (-x, -y, z), (x, -y, z), (x, -y, -z))
    m.quad((x, y, -z), (x, y, z), (-x, y, z), (-x, y, -z))
    m.quad((-x, y, -z), (-x, y, z), (-x, -y, z), (-x, -y, -z))
    m.quad((x, -y, -z), (x, -y, z), (x, y, z), (x, y, -z))
    m.quad((-x, -y, z), (-x, y, z), (x, y, z), (x, -y, z))
    m.quad((-x, y, -z), (-x, -y, -z), (x, -y, -z), (x, y, -z))
    # The six face loops above run inward; reverse each triangle for solid outward faces.
    for i in range(0, len(m.vertices), 3):
        m.vertices[i + 1], m.vertices[i + 2] = m.vertices[i + 2], m.vertices[i + 1]
        m.normals[i:i + 3] = [-n for n in m.normals[i:i + 3]]
    return m.node()


def cylinder(name, radius, depth, inner=0, segments=64):
    m = Mesh(name)
    for i in range(segments):
        a, b = TAU * i / segments, TAU * (i + 1) / segments
        o0, o1 = (radius * math.cos(a), radius * math.sin(a)), (radius * math.cos(b), radius * math.sin(b))
        n0, n1 = (inner * math.cos(a), inner * math.sin(a)), (inner * math.cos(b), inner * math.sin(b))
        low, high = -depth / 2, depth / 2
        m.quad((*o0, low), (*o1, low), (*o1, high), (*o0, high))
        m.quad((*n0, high), (*o0, high), (*o1, high), (*n1, high))
        m.quad((*n1, low), (*o1, low), (*o0, low), (*n0, low))
        if inner: m.quad((*n1, high), (*n1, low), (*n0, low), (*n0, high))
    return m.node()


def gear(teeth, module, depth, mat):
    """20 degree involute profile; visual root fillet remains a simplified straight transition."""
    root = NodePath(f"gear-{teeth}")
    pitch = teeth * module / 2
    base, tip, bottom = pitch * math.cos(math.radians(20)), pitch + module, pitch - 1.25 * module
    inner = pitch * .69
    def inv(radius):
        if radius <= base: return 0
        phi = math.acos(base / radius)
        return math.tan(phi) - phi
    points = []
    for tooth in range(teeth):
        center = TAU * tooth / teeth
        for side, radii in ((-1, (bottom, max(bottom, base), pitch, tip)),
                            (1, (tip, pitch, max(bottom, base), bottom))):
            for r in radii:
                angle = center + side * (math.pi / (2 * teeth) + inv(pitch) - inv(r))
                points.append((r * math.cos(angle), r * math.sin(angle), angle))
    m = Mesh("involute-rim")
    for i, (x0, z0, a0) in enumerate(points):
        x1, z1, a1 = points[(i + 1) % len(points)]
        c0, s0, c1, s1 = inner * math.cos(a0), inner * math.sin(a0), inner * math.cos(a1), inner * math.sin(a1)
        front, back = -depth / 2, depth / 2
        m.quad((c0, front, s0), (x0, front, z0), (x1, front, z1), (c1, front, s1))
        m.quad((c1, back, s1), (x1, back, z1), (x0, back, z0), (c0, back, s0))
        m.quad((x0, back, z0), (x1, back, z1), (x1, front, z1), (x0, front, z0))
        m.quad((c0, front, s0), (c1, front, s1), (c1, back, s1), (c0, back, s0))
    rim = m.node(); rim.reparent_to(root)
    hub = cylinder("hub", pitch * .24, depth * 1.5, inner=pitch * .075, segments=40)
    hub.set_p(90); hub.reparent_to(root)
    for i in range(6):
        angle = TAU * i / 6
        spoke = box("spoke", (pitch * .56, depth * .7, pitch * .10))
        spoke.reparent_to(root); spoke.set_pos(pitch * .46 * math.cos(angle), 0, pitch * .46 * math.sin(angle))
        spoke.set_r(-math.degrees(angle))
    root.set_material(mat, 1)
    return root


# Radius as a function of height: foot, belly, shoulder, narrow neck and flared lip.
VASE_PROFILE = ((0, .29), (.07, .36), (.2, .43), (.48, .61), (.85, .68), (1.13, .60),
                (1.4, .43), (1.56, .26), (1.86, .25), (2.00, .34), (2.06, .35))
VASE_HEIGHT = VASE_PROFILE[-1][0]


def vase_radius(z):
    for (z0, r0), (z1, r1) in zip(VASE_PROFILE, VASE_PROFILE[1:]):
        if z <= z1:
            t = max(0, (z - z0) / (z1 - z0))
            t = t * t * (3 - 2 * t)
            return r0 + (r1 - r0) * t
    return VASE_PROFILE[-1][1]


def porcelain_texture():
    width, height = 768, 512
    image = PNMImage(width, height, 3)
    for y in range(height):
        v = y / height
        for x in range(width):
            u = x / width
            band = any(abs(v - k) < thickness for k, thickness in ((.035, .012), (.11, .005), (.74, .009), (.84, .005), (.96, .013)))
            # Cobalt floral medallions, climbing stems and fine shoulder scallops.
            angle = (u * 10 % 1 - .5) * TAU
            dv = (v - .43) * 16
            rosette = abs(math.hypot(angle, dv) - (1.45 + .28 * math.cos(6 * math.atan2(dv, angle)))) < .19
            vine = .16 < v < .71 and abs(math.sin(u * TAU * 10 + math.sin(v * TAU * 3)) - (v - .43) * 1.5) < .11
            leaf = .17 < v < .70 and abs(math.sin(u * TAU * 20 + v * 40)) > .96 and abs(math.sin(u * TAU * 10 + v * 8)) < .5
            collar = .76 < v < .93 and abs(math.sin(u * TAU * 24) - (v - .84) * 10) < .10
            ink = band or rosette or vine or leaf or collar
            grain = .012 * math.sin(x * 3.71 + y * 2.37)
            color = (.012 + grain, .055 + grain, .22 + grain) if ink else (.89 + grain, .90 + grain, .85 + grain)
            image.set_xel(x, y, *color)
    texture = Texture("handpainted-cobalt"); texture.load(image)
    texture.set_wrap_u(Texture.WM_repeat); texture.set_wrap_v(Texture.WM_clamp)
    texture.set_minfilter(Texture.FT_linear_mipmap_linear); texture.set_magfilter(Texture.FT_linear)
    texture.set_anisotropic_degree(8)
    return texture


def vase_mesh():
    m = Mesh("porcelain-vase")
    rings, segments, thickness = 100, 128, .045
    def point(z, a, inside=False):
        radius = vase_radius(z) - (thickness if inside else 0)
        return radius * math.cos(a), radius * math.sin(a), z
    for j in range(rings):
        z0, z1 = VASE_HEIGHT * j / rings, VASE_HEIGHT * (j + 1) / rings
        for i in range(segments):
            a, b = TAU * i / segments, TAU * (i + 1) / segments
            uv = ((i / segments, j / rings), ((i + 1) / segments, j / rings),
                  ((i + 1) / segments, (j + 1) / rings), (i / segments, (j + 1) / rings))
            # Smooth normals from the derivative of the profile.
            vertices = (point(z0, a), point(z0, b), point(z1, b), point(z1, a))
            normals = []
            for z, angle in ((z0, a), (z0, b), (z1, b), (z1, a)):
                slope = (vase_radius(min(VASE_HEIGHT, z + .001)) - vase_radius(max(0, z - .001))) / .002
                n = Vec3(math.cos(angle), math.sin(angle), -slope); n.normalize(); normals.append(n)
            m.triangle(*vertices[:3], uv[:3], normals[:3])
            m.triangle(vertices[0], vertices[2], vertices[3], (uv[0], uv[2], uv[3]), (normals[0], normals[2], normals[3]))
            m.quad(point(z0, b, True), point(z0, a, True), point(z1, a, True), point(z1, b, True), ((.2, .01),) * 4)
            if j == rings - 1:
                m.quad(point(z1, a), point(z1, b), point(z1, b, True), point(z1, a, True), uv)
    bottom = cylinder("vase-bottom", .29, .05)
    result = m.node(); bottom.reparent_to(result); bottom.set_z(.025)
    return result


def shard_mesh(index, rows=8, columns=20):
    row, col = divmod(index, columns)
    z0, z1 = row * VASE_HEIGHT / rows, (row + 1) * VASE_HEIGHT / rows
    a, b = col * TAU / columns, (col + 1) * TAU / columns
    center = Vec3(vase_radius((z0 + z1) / 2) * math.cos((a + b) / 2),
                  vase_radius((z0 + z1) / 2) * math.sin((a + b) / 2), (z0 + z1) / 2)
    points = []
    for inside in (False, True):
        for z, angle in ((z0, a), (z0, b), (z1, b), (z1, a)):
            r = vase_radius(z) - (.045 if inside else 0)
            points.append(Vec3(r * math.cos(angle), r * math.sin(angle), z) - center)
    m = Mesh(f"shard-{index}")
    uv = ((col / columns, row / rows), ((col + 1) / columns, row / rows),
          ((col + 1) / columns, (row + 1) / rows), (col / columns, (row + 1) / rows))
    m.quad(*points[:4], uv)
    m.quad(points[7], points[6], points[5], points[4])
    for i in range(4):
        k = (i + 1) % 4
        m.quad(points[i], points[i + 4], points[k + 4], points[k], ((.2, .01),) * 4)
    return m.node(), center, points
