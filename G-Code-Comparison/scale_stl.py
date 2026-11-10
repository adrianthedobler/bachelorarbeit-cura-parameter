"""Skaliert ein (binaeres oder ASCII-) STL gleichmaessig um einen Faktor.

Aufruf:  py scale_stl.py <eingabe.stl> <ausgabe.stl> <faktor>
"""
import struct
import sys


def read_triangles(data):
    # ASCII?
    if data[:5].lower() == b"solid" and b"facet" in data[:1024].lower():
        text = data.decode("utf-8", "replace")
        verts = []
        for m in text.split("vertex")[1:]:
            x, y, z = m.split()[:3]
            verts.append((float(x), float(y), float(z)))
        tris = [tuple(verts[i:i + 3]) for i in range(0, len(verts), 3)]
        return tris, None
    # Binaer
    n = struct.unpack_from("<I", data, 80)[0]
    tris, normals, off = [], [], 84
    for _ in range(n):
        vals = struct.unpack_from("<12f", data, off)
        normals.append(vals[0:3])
        tris.append((vals[3:6], vals[6:9], vals[9:12]))
        off += 50
    return tris, normals


def write_binary(path, tris, normals):
    with open(path, "wb") as f:
        f.write(b"scaled by cura setting sweep".ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for i, tri in enumerate(tris):
            nrm = normals[i] if normals else (0.0, 0.0, 0.0)
            f.write(struct.pack("<3f", *nrm))
            for v in tri:
                f.write(struct.pack("<3f", *v))
            f.write(struct.pack("<H", 0))


def bbox(tris):
    mn = [1e18] * 3
    mx = [-1e18] * 3
    for tri in tris:
        for v in tri:
            for c in range(3):
                mn[c] = min(mn[c], v[c])
                mx[c] = max(mx[c], v[c])
    return mn, mx


def main():
    src, dst, factor = sys.argv[1], sys.argv[2], float(sys.argv[3])
    data = open(src, "rb").read()
    tris, normals = read_triangles(data)
    scaled = [tuple(tuple(c * factor for c in v) for v in tri) for tri in tris]
    write_binary(dst, scaled, normals)
    mn0, mx0 = bbox(tris)
    mn1, mx1 = bbox(scaled)
    print(f"Faktor {factor}x, {len(tris)} Dreiecke")
    print("vorher : %.2f x %.2f x %.2f mm" %
          (mx0[0]-mn0[0], mx0[1]-mn0[1], mx0[2]-mn0[2]))
    print("nachher: %.2f x %.2f x %.2f mm" %
          (mx1[0]-mn1[0], mx1[1]-mn1[1], mx1[2]-mn1[2]))


if __name__ == "__main__":
    main()
