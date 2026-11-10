"""Erzeugt das Support-Placement-Testmodell: Ueberhang-Modell + Ausleger.

Auf die Plattenoberseite (z=16) wird ein Galgen gesetzt: ein Pfosten in der
Plattenecke und ein horizontaler Arm, der 10 mm UEBER der Platte schwebt.
Der Arm-Ueberhang steht damit ueber der MODELLOBERFLAECHE (nicht ueber dem
Druckbett):
  - Support Placement "Everywhere":          Arm bekommt Support (steht auf der Platte)
  - Support Placement "Touching Buildplate": Arm bekommt KEINEN Support
Die Zacken-Ueberhaenge (ueber dem Bett) bekommen in beiden Faellen Support.

Pfosten und Arm sind eigene geschlossene Quader, die Platte bzw. einander
leicht durchdringen — CuraEngine vereinigt ueberlappende Volumen automatisch.

Aufruf:  python3 make_support_placement_model.py <ueberhang.stl> <ausgabe.stl>
"""
import math
import struct
import sys

# Pfosten: steht in der Plattenecke, 0.5 mm in die Platte versenkt
POST = (19.0, 23.0, -23.0, -19.0, 15.5, 29.0)   # x0,x1, y0,y1, z0,z1
# Arm: schwebt 10 mm ueber der Plattenoberseite (z=16), ueberlappt den Pfosten
ARM  = ( 7.0, 19.5, -23.0, -19.0, 26.0, 29.0)


def read_binary(path):
    data = open(path, "rb").read()
    n = struct.unpack_from("<I", data, 80)[0]
    tris, off = [], 84
    for _ in range(n):
        vals = struct.unpack_from("<12f", data, off)
        tris.append([list(vals[3:6]), list(vals[6:9]), list(vals[9:12])])
        off += 50
    return tris


def write_binary(path, tris):
    with open(path, "wb") as f:
        f.write(b"support placement model by cura setting sweep".ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for tri in tris:
            ax = tri[1][0]-tri[0][0]; ay = tri[1][1]-tri[0][1]; az = tri[1][2]-tri[0][2]
            bx = tri[2][0]-tri[0][0]; by = tri[2][1]-tri[0][1]; bz = tri[2][2]-tri[0][2]
            nx = ay*bz - az*by; ny = az*bx - ax*bz; nz = ax*by - ay*bx
            ln = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
            f.write(struct.pack("<3f", nx/ln, ny/ln, nz/ln))
            for v in tri:
                f.write(struct.pack("<3f", *v))
            f.write(struct.pack("<H", 0))


def box(x0, x1, y0, y1, z0, z1):
    """Geschlossener Quader aus 12 Dreiecken, Normalen nach aussen."""
    tris = []
    def q(a, b, c, d):
        tris.append([list(a), list(b), list(c)])
        tris.append([list(a), list(c), list(d)])
    q((x0,y0,z0), (x0,y1,z0), (x1,y1,z0), (x1,y0,z0))   # Boden (-z)
    q((x0,y0,z1), (x1,y0,z1), (x1,y1,z1), (x0,y1,z1))   # Deckel (+z)
    q((x0,y0,z0), (x1,y0,z0), (x1,y0,z1), (x0,y0,z1))   # vorne (-y)
    q((x0,y1,z0), (x0,y1,z1), (x1,y1,z1), (x1,y1,z0))   # hinten (+y)
    q((x0,y0,z0), (x0,y0,z1), (x0,y1,z1), (x0,y1,z0))   # links (-x)
    q((x1,y0,z0), (x1,y1,z0), (x1,y1,z1), (x1,y0,z1))   # rechts (+x)
    return tris


def main():
    src, dst = sys.argv[1], sys.argv[2]
    tris = read_binary(src)
    tris += box(*POST)
    tris += box(*ARM)
    write_binary(dst, tris)
    print(f"Geschrieben: {dst} ({len(tris)} Dreiecke)")
    print(f"Pfosten: x {POST[0]}..{POST[1]}, y {POST[2]}..{POST[3]}, z {POST[4]}..{POST[5]}")
    print(f"Arm:     x {ARM[0]}..{ARM[1]}, y {ARM[2]}..{ARM[3]}, z {ARM[4]}..{ARM[5]}")


if __name__ == "__main__":
    main()
