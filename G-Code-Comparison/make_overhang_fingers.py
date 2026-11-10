"""Skaliert die Slicer-Test-STL in Z und schneidet die fuenf Zacken-Spitzen
schraeg ab — wahlweise als Ueberhang oder als Aufstieg (Rampe).

Modus "ueberhang": Die OBERE Kante der Spitze (y=50) bleibt stehen; die
Spitzenflaeche kippt schraeg nach unten/innen -> Ueberhang unter der Schraege.

Modus "aufstieg": Genau umgekehrt — die UNTERE Kante der Spitze bleibt am
Boden stehen; die Spitzenflaeche kippt schraeg nach oben/innen -> Rampe, die
vom Boden bis auf Kastenhoehe ansteigt (kein Ueberhang, ohne Support druckbar).

Ist der noetige Rueckversatz D groesser als D_MAX (Zackenlaenge), laeuft die
Schraege nur ueber einen Teil der Hoehe und der Rest ist senkrecht — der
Winkel bleibt exakt erhalten. Die betroffenen Seitenwaende werden dann ueber
Rand-Extraktion + Faecher-Triangulation neu aufgebaut.

Der Donut (Ring r 7.5..17.5) behaelt seine Originalgroesse (4 mm hoch, 1 mm
in der Platte versenkt), relativ zur neuen Plattenoberkante.

Aufruf:  python3 make_overhang_fingers.py <eingabe.stl> <ausgabe.stl> [ueberhang|aufstieg]
"""
import math
import struct
import sys

Z_SCALE = 4.0          # Z-Hochskalierung ab Original (Platte 4 mm -> 16 mm)
FINGER_TIP_Y = 50.0    # Y-Position der Zackenspitzen
FINGER_TOP_Z = 4.0     # Zackenhoehe VOR Skalierung
D_MAX = 22.0           # max. Rueckversatz (Zacken sind 25 mm lang)
EPS = 0.01

DONUT_R_MAX = 19.0     # alles zentral innerhalb dieses Radius
DONUT_BOT_Z = 3.0      # Donut-Unterseite VOR Skalierung
DONUT_TOP_Z = 7.0      # Donut-Oberseite VOR Skalierung
PLATE_TOP_Z = 4.0      # Plattenoberkante VOR Skalierung

# (x_min, x_max, Winkel in Grad zur Vertikalen)
FINGERS = [
    (-25.01, -19.99, 30.0),
    (-14.51, -10.49, 40.0),
    ( -1.51,   1.51, 50.0),
    ( 11.24,  13.26, 60.0),
    ( 23.99,  25.01, 70.0),
]


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
        f.write(b"overhang fingers by cura setting sweep".ljust(80, b"\0"))
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


def key(v):
    return (round(v[0], 3), round(v[1], 3), round(v[2], 3))


def quad(a, b, c, d, outward):
    """Zwei Dreiecke fuer das Viereck a-b-c-d, Winding nach outward-Vektor."""
    out = []
    for tri in ([a, b, c], [a, c, d]):
        ax = tri[1][0]-tri[0][0]; ay = tri[1][1]-tri[0][1]; az = tri[1][2]-tri[0][2]
        bx = tri[2][0]-tri[0][0]; by = tri[2][1]-tri[0][1]; bz = tri[2][2]-tri[0][2]
        n = (ay*bz - az*by, az*bx - ax*bz, ax*by - ay*bx)
        if n[0]*outward[0] + n[1]*outward[1] + n[2]*outward[2] < 0:
            tri = [tri[0], tri[2], tri[1]]
        out.append([list(v) for v in tri])
    return out


def rebuild_wall(tris, wall_x, y_tip, corner_z, ref_z, v_mid, v_far):
    """Baut eine Seitenwand (Ebene x=wall_x) mit Kerbe neu auf.

    Ersetzt im Wandrand den Eckpunkt (y_tip, corner_z) durch die zwei Punkte
    v_mid/v_far, wobei v_mid dem Nachbar-Eckpunkt (y_tip, ref_z) zugewandt
    liegt. Trianguliert als Faecher um v_mid (Kerbenpunkt, sieht alles).
    """
    wall = [t for t in tris if all(abs(v[0] - wall_x) < EPS for v in t)]
    assert wall, f"Keine Wand-Dreiecke in Ebene x={wall_x}"
    wall_ids = {id(t) for t in wall}

    # Gerichteter Rand: Kanten, deren Gegenrichtung nicht in der Wand liegt
    directed = set()
    for t in wall:
        ks = [key(v) for v in t]
        for i in range(3):
            directed.add((ks[i], ks[(i+1) % 3]))
    succ = {}
    for a, b in directed:
        if (b, a) not in directed:
            assert a not in succ, f"Rand nicht eindeutig bei {a}"
            succ[a] = b

    start = next(iter(succ))
    loop = [start]
    while True:
        nxt = succ[loop[-1]]
        if nxt == start:
            break
        loop.append(nxt)
    assert len(loop) == len(succ), "Rand zerfaellt in mehrere Schleifen"

    # Eckpunkt (y_tip, corner_z) durch Kerbenpfad ersetzen
    idx = None
    for i, v in enumerate(loop):
        if abs(v[1] - y_tip) < EPS and abs(v[2] - corner_z) < EPS:
            idx = i
            break
    assert idx is not None, f"Eckpunkt nicht im Rand (x={wall_x})"
    is_ref = lambda v: abs(v[1] - y_tip) < EPS and abs(v[2] - ref_z) < EPS
    if is_ref(loop[idx - 1]):
        repl = [v_mid, v_far]   # vom Referenzpunkt kommend: erst Kerbe
    else:
        repl = [v_far, v_mid]
    loop = loop[:idx] + repl + loop[idx+1:]

    tris[:] = [t for t in tris if id(t) not in wall_ids]
    m = loop.index(v_mid)
    loop = loop[m:] + loop[:m]
    for i in range(1, len(loop) - 1):
        tris.append([list(loop[0]), list(loop[i]), list(loop[i+1])])


def main():
    src, dst = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "ueberhang"
    assert mode in ("ueberhang", "aufstieg"), f"Unbekannter Modus: {mode}"
    tris = read_binary(src)

    # 1) Z hochskalieren
    for tri in tris:
        for v in tri:
            v[2] *= Z_SCALE

    # 1b) Donut auf Originalgroesse zurueckrechnen (Fixpunkt Plattenoberkante)
    zb_s = DONUT_BOT_Z * Z_SCALE
    new_bot = PLATE_TOP_Z * Z_SCALE - (PLATE_TOP_Z - DONUT_BOT_Z)
    for tri in tris:
        for v in tri:
            if math.hypot(v[0], v[1]) < DONUT_R_MAX and v[2] > EPS:
                v[2] = new_bot + (v[2] - zb_s) / Z_SCALE

    height = FINGER_TOP_Z * Z_SCALE  # Zackenhoehe nach Skalierung

    # 2) Zackenspitzen schraeg schneiden
    for x_min, x_max, angle in FINGERS:
        tan_a = math.tan(math.radians(angle))
        d = min(height * tan_a, D_MAX)
        z_run = round(d / tan_a, 3)          # vertikale Spanne der Schraege
        full = z_run >= height - EPS
        y_new = round(FINGER_TIP_Y - d, 3)

        # 2a) Spitzenflaechen-Dreiecke entfernen (alle 3 Ecken bei y=50)
        def is_tip(tri):
            return all(abs(v[1] - FINGER_TIP_Y) < EPS and x_min <= v[0] <= x_max
                       for v in tri)
        tip_tris = [t for t in tris if is_tip(t)]
        assert len(tip_tris) == 2, f"Zacke {angle}: {len(tip_tris)} Spitzen-Dreiecke"
        xs = sorted({round(v[0], 4) for t in tip_tris for v in t})
        x_l, x_r = xs[0], xs[-1]
        tris[:] = [t for t in tris if not is_tip(t)]

        if mode == "ueberhang":
            # Oberkante bleibt, Unterkante wandert nach innen
            corner_z, keep_z = 0.0, height
            z_mid = round(height - z_run, 3)         # unteres Ende der Schraege
            mid_l, mid_r = (x_l, y_new, z_mid), (x_r, y_new, z_mid)
            far_l, far_r = (x_l, y_new, 0.0), (x_r, y_new, 0.0)
            keep_l = (x_l, FINGER_TIP_Y, height)
            keep_r = (x_r, FINGER_TIP_Y, height)
            slant_out = (0.0, height - z_mid, -d)    # nach unten/vorne
            vert_quad = (mid_l, mid_r, far_r, far_l)
        else:
            # Aufstieg: Unterkante bleibt, Oberkante wandert nach innen
            corner_z, keep_z = height, 0.0
            z_mid = z_run                            # oberes Ende der Schraege
            mid_l, mid_r = (x_l, y_new, z_mid), (x_r, y_new, z_mid)
            far_l, far_r = (x_l, y_new, height), (x_r, y_new, height)
            keep_l = (x_l, FINGER_TIP_Y, 0.0)
            keep_r = (x_r, FINGER_TIP_Y, 0.0)
            slant_out = (0.0, z_mid, d)              # nach oben/vorne
            vert_quad = (mid_l, mid_r, far_r, far_l)

        # 2b) Waende mit Kerbe neu aufbauen (nur wenn Schraege nicht durchlaeuft)
        if not full:
            rebuild_wall(tris, x_l, FINGER_TIP_Y, corner_z, keep_z,
                         key(mid_l), key(far_l))
            rebuild_wall(tris, x_r, FINGER_TIP_Y, corner_z, keep_z,
                         key(mid_r), key(far_r))

        # 2c) verschobene Kante nach innen setzen (Boden- bzw. Deckflaeche;
        #     bei durchlaufender Schraege auch die Seitenwaende)
        n_moved = 0
        for tri in tris:
            for v in tri:
                if (x_min <= v[0] <= x_max and abs(v[1] - FINGER_TIP_Y) < EPS
                        and abs(v[2] - corner_z) < EPS):
                    v[1] = y_new
                    n_moved += 1

        # 2d) neue Spitzenflaechen: Schraege + ggf. senkrechter Rest
        tris.extend(quad(keep_l, keep_r, mid_r, mid_l, slant_out))
        if not full:
            tris.extend(quad(*vert_quad, (0.0, 1.0, 0.0)))

        print(f"Zacke x[{x_min:6.2f}..{x_max:6.2f}]  Winkel {angle:4.1f} Grad  "
              f"D={d:5.2f} mm  Schraege {'durchgehend' if full else f'{z_run:.1f} mm'}"
              f"  ({n_moved} Ecken verschoben)")

    write_binary(dst, tris)
    print(f"\nModus '{mode}' geschrieben: {dst} ({len(tris)} Dreiecke)")


if __name__ == "__main__":
    main()
