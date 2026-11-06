"""Build compact equirectangular backgrounds from Minecraft cubemap faces."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "nonebot_plugin_mcserver_status_check" / "assets" / "panoramas" / "history"
OUTPUT_SIZE = (1536, 768)
JPEG_QUALITY = 82


def _project_cubemap(faces: list[np.ndarray]) -> np.ndarray:
    width, height = OUTPUT_SIZE
    face_size = faces[0].shape[0]
    if any(face.shape[:2] != (face_size, face_size) for face in faces):
        raise ValueError("All six panorama faces must be square and have the same size")

    # Pad each face horizontally so bilinear samples at cube edges cannot bleed
    # into the neighboring face in the stacked atlas.
    padded_faces = [
        cv2.copyMakeBorder(face, 0, 0, 1, 1, cv2.BORDER_REPLICATE)
        for face in faces
    ]
    atlas = np.concatenate(padded_faces, axis=1)

    longitude = (
        (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
    ) * (2 * np.pi)
    latitude = (
        0.5 - (np.arange(height, dtype=np.float32) + 0.5) / height
    ) * np.pi
    cos_latitude = np.cos(latitude)[:, None]
    ray_x = cos_latitude * np.sin(longitude)[None, :]
    ray_y = np.broadcast_to(np.sin(latitude)[:, None], (height, width))
    ray_z = cos_latitude * np.cos(longitude)[None, :]

    abs_x = np.abs(ray_x)
    abs_y = np.abs(ray_y)
    abs_z = np.abs(ray_z)
    x_major = (abs_x >= abs_y) & (abs_x >= abs_z)
    y_major = (~x_major) & (abs_y >= abs_z)
    z_major = ~(x_major | y_major)

    face_index = np.empty((height, width), dtype=np.uint8)
    local_u = np.empty((height, width), dtype=np.float32)
    local_v = np.empty((height, width), dtype=np.float32)

    mask = x_major & (ray_x >= 0)
    face_index[mask] = 1  # right (+X)
    local_u[mask] = -ray_z[mask] / abs_x[mask]
    local_v[mask] = -ray_y[mask] / abs_x[mask]

    mask = x_major & (ray_x < 0)
    face_index[mask] = 3  # left (-X)
    local_u[mask] = ray_z[mask] / abs_x[mask]
    local_v[mask] = -ray_y[mask] / abs_x[mask]

    mask = y_major & (ray_y >= 0)
    face_index[mask] = 4  # top (+Y)
    local_u[mask] = ray_x[mask] / abs_y[mask]
    local_v[mask] = ray_z[mask] / abs_y[mask]

    mask = y_major & (ray_y < 0)
    face_index[mask] = 5  # bottom (-Y)
    local_u[mask] = ray_x[mask] / abs_y[mask]
    local_v[mask] = -ray_z[mask] / abs_y[mask]

    mask = z_major & (ray_z >= 0)
    face_index[mask] = 0  # front (+Z)
    local_u[mask] = ray_x[mask] / abs_z[mask]
    local_v[mask] = -ray_y[mask] / abs_z[mask]

    mask = z_major & (ray_z < 0)
    face_index[mask] = 2  # back (-Z)
    local_u[mask] = -ray_x[mask] / abs_z[mask]
    local_v[mask] = -ray_y[mask] / abs_z[mask]

    padded_width = face_size + 2
    map_x = (
        face_index.astype(np.float32) * padded_width
        + 1
        + (local_u + 1) * 0.5 * (face_size - 1)
    )
    map_y = (local_v + 1) * 0.5 * (face_size - 1)
    return cv2.remap(
        atlas,
        map_x,
        map_y,
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def main() -> None:
    manifest_path = HISTORY_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir = HISTORY_DIR / "equirectangular"
    output_dir.mkdir(parents=True, exist_ok=True)

    for set_name, entry in manifest["background_sets"].items():
        faces_dir = HISTORY_DIR / entry["directory"]
        faces = []
        for index in range(6):
            with Image.open(faces_dir / f"panorama_{index}.png") as source:
                faces.append(np.asarray(source.convert("RGB")))

        panorama = Image.fromarray(_project_cubemap(faces))
        filename = f"{set_name}.jpg"
        output_path = output_dir / filename
        panorama.save(
            output_path,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=2,
            optimize=True,
            progressive=True,
        )
        entry["equirectangular"] = f"equirectangular/{filename}"
        entry["equirectangular_size"] = list(OUTPUT_SIZE)
        print(f"{set_name}: {output_path.stat().st_size / 1024:.1f} KiB")

    manifest["equirectangular_projection"] = {
        "format": "2:1 equirectangular 360-degree panorama",
        "size": list(OUTPUT_SIZE),
        "encoding": f"JPEG quality {JPEG_QUALITY}",
        "center_direction": "panorama_0 (front)",
        "face_order": ["front", "right", "back", "left", "top", "bottom"],
        "sampling": "bilinear",
        "note": "Generated from the original six-face cubemap; source faces are excluded from built distributions.",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
