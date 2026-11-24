#!/usr/bin/env python3
import re

import numpy as np

import inkex
from inkex.elements import Gradient, MeshGradient
from inkex.paths import Path

from simplex_noise import SimplexNoise


class NoiseMeshGradient(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--rows", type=int, default=4)
        pars.add_argument("--cols", type=int, default=4)
        pars.add_argument("--noise_scale", type=float, default=3.0)
        pars.add_argument("--seed", type=int, default=0)
        pars.add_argument(
            "--noise_type",
            type=str,
            default="simplex",
            choices=["simplex", "fbm", "turbulence"],
            dest="noise_type",
        )
        pars.add_argument("--octaves", type=int, default=4)
        pars.add_argument("--lacunarity", type=float, default=2.0)
        pars.add_argument("--gain", type=float, default=0.5)

    def _sample_noise_batch(self, noise, nx, ny):
        kind = self.options.noise_type
        if kind == "fbm":
            return noise.fbm_batch(nx, ny,
                                    octaves=self.options.octaves,
                                    lacunarity=self.options.lacunarity,
                                    gain=self.options.gain)
        if kind == "turbulence":
            return noise.turbulence_batch(nx, ny,
                                            octaves=self.options.octaves,
                                            lacunarity=self.options.lacunarity,
                                            gain=self.options.gain)
        return noise.noise_batch(nx, ny)

    def _get_gradient_stops(self, elem):
        """Parse the gradient stops from the element's fill.

        Returns a sorted list of (offset, (r, g, b)) tuples, or None if the
        fill is not a gradient reference. Uses inkex's Gradient.stops so
        that linked (xlink:href) gradients are resolved automatically.
        """
        fill = elem.style.get("fill", "")
        match = re.search(r'url\(#([^)]+)\)', fill)
        if not match:
            return None

        grad_id = match.group(1)
        grad = self.svg.getElementById(grad_id)
        if grad is None or not isinstance(grad, Gradient):
            return None

        stops = []
        for stop in grad.stops:
            offset_str = stop.get("offset", "0").strip()
            if offset_str.endswith("%"):
                offset = float(offset_str[:-1]) / 100.0
            else:
                offset = float(offset_str)

            try:
                color = stop.get_computed_style("stop-color") or inkex.Color("#000000")
                opacity = stop.get_computed_style("stop-opacity")
                color.alpha *= opacity
            except Exception:
                color = inkex.Color("#000000")
            stops.append(
                (
                    offset,
                    color.red, color.green, color.blue, color.alpha
                )
            )

        return np.asarray(stops)

    def _sample_gradient(self, stops, t):
        """Linearly interpolate the gradient at position t (0~1)."""
        xp = stops[:,0]
        result = [
            np.interp(t, xp, stops[:,i])
            for i in range(1, 5)
        ]

        return np.dstack(result)

    def effect(self):
        if not self.svg.selection:
            inkex.errormsg("Please select an object with a gradient fill.")
            return

        noise = SimplexNoise(seed=self.options.seed)
        rows = max(1, self.options.rows)
        cols = max(1, self.options.cols)
        noise_scale = self.options.noise_scale

        for elem in self.svg.selection:
            bbox = elem.bounding_box()
            if bbox is None:
                continue

            stops = self._get_gradient_stops(elem)
            if not stops.any():
                inkex.errormsg(
                    f"Object {elem.get_id()} has no gradient fill, skipping."
                )
                continue

            w = bbox.width
            h = bbox.height
            if w < 1e-9 or h < 1e-9:
                continue

            # Precompute the noise value at every mesh node once.
            # Grid nodes are (rows+1) x (cols+1).
            nx_vals = np.linspace(0.0, 1.0, cols + 1)
            ny_vals = np.linspace(0.0, 1.0, rows + 1)
            gx, gy = np.meshgrid(nx_vals, ny_vals)
            t_grid = self._sample_noise_batch(noise, gx * noise_scale, gy * noise_scale)

            # Map each node's noise value to a gradient sample position
            # and resolve it to an RGB hex color.
            t_grid -= t_grid.min()
            t_grid /= t_grid.max()
            color_grid = self._sample_gradient(stops, t_grid)

            # Create the mesh skeleton.
            mesh = MeshGradient.new_mesh(
                pos=(bbox.left, bbox.top), rows=rows, cols=cols
            )

            corners = [
                (w / cols, 0),
                (0, h / rows),
                (-w / cols, 0),
                (0, -h / rows),
            ]

            def _mesh_patch(r, c):
                edges = []
                colors = []
                if r == 0:
                    edges.append(corners[0])
                    colors.append(color_grid[r,c])
                edges.append(corners[1])
                colors.append(color_grid[r,c + 1])
                edges.append(corners[2])
                colors.append(color_grid[r + 1,c + 1])
                if c == 0:
                    edges.append(corners[3])
                    colors.append(color_grid[r + 1,c])
                return edges, colors

            # Build each patch from the precomputed node colors.
            for r in range(rows):
                for c in range(cols):
                    edges, colors = _mesh_patch(r, c)

                    mesh[r][c].stops(
                        [
                            Path("l {:.4f},{:.4f}".format(*e))
                            for e in edges
                        ],
                        [
                            "#{:02x}{:02x}{:02x}".format(*c[:3].astype(np.int64))
                            for c in colors
                        ]
                    )
                    # alpha for stops
                    for i, stop in enumerate(mesh[r][c]):
                        stop.style['stop-opacity'] = float(colors[i][3])

            # Add the mesh to the document and apply it as the fill.
            self.svg.defs.append(mesh)
            mesh.set_random_id("meshgradient")
            elem.style["fill"] = f"url(#{mesh.get_id()})"


if __name__ == "__main__":
    NoiseMeshGradient().run()