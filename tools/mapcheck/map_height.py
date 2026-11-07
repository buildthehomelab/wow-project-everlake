#!/usr/bin/env python3
"""Ground height from the server's extracted .map files, the same way the worldserver's GridMap::getHeight does it
(terrain only, no vmaps). For checking extracted terrain without starting the server.

    tools/mapcheck/map_height.py <data-dir> <map-id> <x> <y> [<x> <y> ...]
    tools/mapcheck/map_height.py data 530 10349.6 -6357.29

Prints one line per point: file, area id, terrain height.
"""
import os
import struct
import sys

SIZE_OF_GRIDS = 533.3333
CENTER_GRID_ID = 32
MAP_RESOLUTION = 128

FLAG_NO_HEIGHT, FLAG_INT16, FLAG_INT8 = 0x1, 0x2, 0x4


def load_tile(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, version, build, area_off, area_size, height_off, height_size = struct.unpack_from("<4sII4I", data, 0)
    if magic != b"MAPS":
        raise SystemExit(f"{path}: not a .map file")
    area_magic, area_flags, grid_area = struct.unpack_from("<4sHH", data, area_off)
    areas = None if area_flags & 0x1 else struct.unpack_from("<256H", data, area_off + 8)
    h_magic, h_flags, grid_height, grid_max = struct.unpack_from("<4sIff", data, height_off)
    pos = height_off + 16
    if h_flags & FLAG_NO_HEIGHT:
        return {"area": grid_area, "areas": areas, "flat": grid_height}
    if h_flags & FLAG_INT16:
        fmt, size, mult = "H", 2, (grid_max - grid_height) / 65535
    elif h_flags & FLAG_INT8:
        fmt, size, mult = "B", 1, (grid_max - grid_height) / 255
    else:
        fmt, size, mult = "f", 4, None
    v9 = struct.unpack_from(f"<{129 * 129}{fmt}", data, pos)
    v8 = struct.unpack_from(f"<{128 * 128}{fmt}", data, pos + 129 * 129 * size)
    if mult is not None:  # int forms store (h - gridHeight) / mult
        v9 = [grid_height + v * mult for v in v9]
        v8 = [grid_height + v * mult for v in v8]
    return {"area": grid_area, "areas": areas, "v9": v9, "v8": v8, "build": build}


def area(tile, x, y):
    if tile["areas"] is None:
        return tile["area"]
    lx = int(16 * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)) & 15
    ly = int(16 * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)) & 15
    return tile["areas"][lx * 16 + ly]


def height(tile, x, y):
    if "flat" in tile:
        return tile["flat"]
    v9, v8 = tile["v9"], tile["v8"]
    x = MAP_RESOLUTION * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)
    y = MAP_RESOLUTION * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)
    xi, yi = int(x), int(y)
    x -= xi
    y -= yi
    xi &= MAP_RESOLUTION - 1
    yi &= MAP_RESOLUTION - 1
    h5 = 2 * v8[xi * 128 + yi]
    if x + y < 1:
        if x > y:
            h1, h2 = v9[xi * 129 + yi], v9[(xi + 1) * 129 + yi]
            a, b, c = h2 - h1, h5 - h1 - h2, h1
        else:
            h1, h3 = v9[xi * 129 + yi], v9[xi * 129 + yi + 1]
            a, b, c = h5 - h1 - h3, h3 - h1, h1
    else:
        if x > y:
            h2, h4 = v9[(xi + 1) * 129 + yi], v9[(xi + 1) * 129 + yi + 1]
            a, b, c = h2 + h4 - h5, h4 - h2, h5 - h4
        else:
            h3, h4 = v9[xi * 129 + yi + 1], v9[(xi + 1) * 129 + yi + 1]
            a, b, c = h4 - h3, h3 + h4 - h5, h5 - h4
    return a * x + b * y + c


def main():
    if len(sys.argv) < 5 or len(sys.argv) % 2 == 0:
        raise SystemExit(__doc__)
    data_dir, map_id = sys.argv[1], int(sys.argv[2])
    coords = [float(v) for v in sys.argv[3:]]
    tiles = {}
    for x, y in zip(coords[0::2], coords[1::2]):
        gx = int(CENTER_GRID_ID - x / SIZE_OF_GRIDS)
        gy = int(CENTER_GRID_ID - y / SIZE_OF_GRIDS)
        name = f"{map_id:04}_{gx:02}_{gy:02}.map"
        path = os.path.join(data_dir, "maps", name)
        if not os.path.exists(path):
            print(f"{x:10.2f} {y:10.2f}  {name}  MISSING")
            continue
        tile = tiles.setdefault(path, load_tile(path))
        print(f"{x:10.2f} {y:10.2f}  {name}  area {area(tile, x, y):5}  z {height(tile, x, y):8.3f}")


if __name__ == "__main__":
    main()
