"""Ground and water heights from TrinityCore's extracted .map tiles (the mapextractor's output, version 10), read the way
the worldserver reads them (GridMap::getHeight, getLiquidLevel), so a spawn placed at that height stands where the
server puts the ground. Only the terrain: buildings, caves and bridges are in the vmaps, which this doesn't read; over a hole in the terrain
there is no height.

    terrain.py MAPS_DIR MAP X Y        print the ground and water height at a point
"""
import os
import struct
import sys

MAP_RESOLUTION = 128
CENTER_GRID_ID = 32
SIZE_OF_GRIDS = 533.3333333
NO_HEIGHT, AS_INT16, AS_INT8 = 0x1, 0x2, 0x4
LIQUID_NO_TYPE, LIQUID_NO_HEIGHT = 0x1, 0x2
VERSION = 10


class Tile:
    def __init__(self, data):
        magic, version, build = struct.unpack_from("<4sII", data, 0)
        if magic != b"MAPS" or version != VERSION:
            raise ValueError(f"not a version {VERSION} .map tile ({magic!r} {version})")
        self.build = build
        (_, _, h_off, h_size, l_off, l_size, holes_off, holes_size) = struct.unpack_from("<8I", data, 12)
        # holes: 16 x 16 cells of 8 x 8 bits, where the terrain is cut away (cave mouths, buildings sunk into the ground)
        self.holes = data[holes_off:holes_off + holes_size] if holes_size else None
        self.v9 = self.v8 = None
        self.flat = 0.0
        if h_size:
            fourcc, flags, grid_h, grid_max = struct.unpack_from("<4sIff", data, h_off)
            self.flat = grid_h
            if not flags & NO_HEIGHT:
                p = h_off + 16
                if flags & AS_INT16:
                    mult = (grid_max - grid_h) / 65535
                    v9 = struct.unpack_from(f"<{129 * 129}H", data, p)
                    v8 = struct.unpack_from(f"<{128 * 128}H", data, p + 129 * 129 * 2)
                elif flags & AS_INT8:
                    mult = (grid_max - grid_h) / 255
                    v9 = struct.unpack_from(f"<{129 * 129}B", data, p)
                    v8 = struct.unpack_from(f"<{128 * 128}B", data, p + 129 * 129)
                else:
                    mult = None
                    v9 = struct.unpack_from(f"<{129 * 129}f", data, p)
                    v8 = struct.unpack_from(f"<{128 * 128}f", data, p + 129 * 129 * 4)
                if mult is None:
                    self.v9, self.v8 = v9, v8
                else:
                    self.v9 = [v * mult + grid_h for v in v9]
                    self.v8 = [v * mult + grid_h for v in v8]
        self.liquid = None
        if l_size:
            fourcc, lflags, _, _, off_x, off_y, width, height, level = struct.unpack_from("<4sBBHBBBBf", data, l_off)
            p = l_off + 16
            cell_flags = None
            if not lflags & LIQUID_NO_TYPE:
                p += 16 * 16 * 2
                cell_flags = struct.unpack_from("<256B", data, p)
                p += 256
            heights = None if lflags & LIQUID_NO_HEIGHT else struct.unpack_from(f"<{width * height}f", data, p)
            self.liquid = (off_x, off_y, width, height, level, cell_flags, heights)

    def hole(self, xi, yi):
        if not self.holes:
            return False
        cell_row, cell_col = xi // 8, yi // 8
        return bool(self.holes[(cell_row * 16 + cell_col) * 8 + xi % 8] & (1 << (yi - cell_col * 8)))

    def height(self, x, y):
        """The ground height, or None over a hole in the terrain (TrinityCore's INVALID_HEIGHT)."""
        if self.v9 is None:
            return self.flat
        fx = MAP_RESOLUTION * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)
        fy = MAP_RESOLUTION * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)
        xi, yi = int(fx), int(fy)
        fx -= xi
        fy -= yi
        xi &= MAP_RESOLUTION - 1
        yi &= MAP_RESOLUTION - 1
        if self.hole(xi, yi):
            return None
        v9, v8 = self.v9, self.v8
        h5 = 2 * v8[xi * 128 + yi]
        if fx + fy < 1:
            if fx > fy:
                h1, h2 = v9[xi * 129 + yi], v9[(xi + 1) * 129 + yi]
                a, b, c = h2 - h1, h5 - h1 - h2, h1
            else:
                h1, h3 = v9[xi * 129 + yi], v9[xi * 129 + yi + 1]
                a, b, c = h5 - h1 - h3, h3 - h1, h1
        elif fx > fy:
            h2, h4 = v9[(xi + 1) * 129 + yi], v9[(xi + 1) * 129 + yi + 1]
            a, b, c = h2 + h4 - h5, h4 - h2, h5 - h4
        else:
            h3, h4 = v9[xi * 129 + yi + 1], v9[(xi + 1) * 129 + yi + 1]
            a, b, c = h4 - h3, h3 + h4 - h5, h5 - h4
        return a * fx + b * fy + c

    def water(self, x, y):
        """The water surface at the point, or None."""
        if not self.liquid:
            return None
        off_x, off_y, width, height, level, cell_flags, heights = self.liquid
        fx = MAP_RESOLUTION * (CENTER_GRID_ID - x / SIZE_OF_GRIDS)
        fy = MAP_RESOLUTION * (CENTER_GRID_ID - y / SIZE_OF_GRIDS)
        xi, yi = int(fx) & (MAP_RESOLUTION - 1), int(fy) & (MAP_RESOLUTION - 1)
        if cell_flags is not None and not cell_flags[(xi >> 3) * 16 + (yi >> 3)]:
            return None
        if heights is None:
            return level
        cx, cy = xi - off_y, yi - off_x
        if not (0 <= cx < height and 0 <= cy < width):
            return None
        return heights[cx * width + cy]


class Terrain:
    """Tiles of one extracted maps folder, loaded as needed."""

    def __init__(self, folder):
        if not os.path.isdir(folder):
            raise SystemExit(f"{folder}: no extracted maps folder")
        self.folder = folder
        self.tiles = {}

    def tile(self, map_id, x, y):
        gx, gy = int(CENTER_GRID_ID - x / SIZE_OF_GRIDS), int(CENTER_GRID_ID - y / SIZE_OF_GRIDS)
        key = (map_id, gx, gy)
        if key not in self.tiles:
            path = os.path.join(self.folder, f"{map_id:04d}_{gx:02d}_{gy:02d}.map")
            self.tiles[key] = Tile(open(path, "rb").read()) if os.path.exists(path) else None
        return self.tiles[key]

    def ground(self, map_id, x, y):
        t = self.tile(map_id, x, y)
        return None if t is None else t.height(x, y)

    def water(self, map_id, x, y):
        t = self.tile(map_id, x, y)
        return None if t is None else t.water(x, y)

    def build(self):
        return next((t.build for t in self.tiles.values() if t), None)


if __name__ == "__main__":
    folder, m, x, y = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    t = Terrain(folder)
    print(f"ground {t.ground(m, x, y)}, water {t.water(m, x, y)}")
