"""Generate a simple 20 mm ASCII STL cube for slicing tests."""
import os

def make_cube(path, s=20.0):
    v = [(0,0,0),(s,0,0),(s,s,0),(0,s,0),(0,0,s),(s,0,s),(s,s,s),(0,s,s)]
    faces = [(0,3,2),(0,2,1),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
             (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    def normal(a,b,c):
        ux,uy,uz = b[0]-a[0],b[1]-a[1],b[2]-a[2]
        vx,vy,vz = c[0]-a[0],c[1]-a[1],c[2]-a[2]
        return (uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx)
    out = ["solid cube"]
    for f in faces:
        a,b,c = v[f[0]],v[f[1]],v[f[2]]
        nx,ny,nz = normal(a,b,c)
        out.append(f"facet normal {nx} {ny} {nz}")
        out.append("outer loop")
        for p in (a,b,c):
            out.append(f"vertex {p[0]} {p[1]} {p[2]}")
        out.append("endloop")
        out.append("endfacet")
    out.append("endsolid cube")
    with open(path, "w") as fh:
        fh.write("\n".join(out))

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "cube.stl")
    make_cube(p)
    print("wrote", p)
