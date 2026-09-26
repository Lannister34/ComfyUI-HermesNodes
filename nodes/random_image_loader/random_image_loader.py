import os
import random
import re
import sys
import uuid

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}
PREVIEW_MAX_SIDE = 1024
_BARE_DRIVE = re.compile(r"^[A-Za-z]:$")


def normalize_folder(path):
    """Strip the path; on Windows a bare "D:" is the drive root, not the drive's current directory."""
    path = path.strip()
    if sys.platform == "win32" and _BARE_DRIVE.match(path):
        return path + "\\"
    return path


def list_images(folder_path, recursive):
    if recursive:
        files = [
            os.path.join(root, name)
            for root, _, names in os.walk(folder_path)
            for name in names
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
        ]
    else:
        files = [
            entry.path for entry in os.scandir(folder_path)
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in SUPPORTED_EXTENSIONS
        ]
    return sorted(files)


def save_preview(img):
    """Write a downscaled copy to temp/ so the front end can show it through the standard /view route."""
    preview = img.copy()
    preview.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
    temp_dir = folder_paths.get_temp_directory()
    os.makedirs(temp_dir, exist_ok=True)
    filename = f"hermes_random_image_{uuid.uuid4().hex[:12]}.jpg"
    preview.save(os.path.join(temp_dir, filename), quality=90)
    return {"filename": filename, "subfolder": "", "type": "temp"}


class RandomImageLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder_path": ("STRING", {"default": "", "multiline": False, "tooltip": "Folder to pick images from. Use the Choose Folder button or type a path."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF, "tooltip": "Same seed + same folder contents = same image."}),
                "recursive": ("BOOLEAN", {"default": False, "tooltip": "Also pick from subfolders."}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "load_random"
    CATEGORY = "hermes/image"
    DESCRIPTION = "Loads a seeded random image from a folder (png, jpg, webp, bmp, tiff)."

    def load_random(self, folder_path, seed, recursive):
        folder_path = normalize_folder(folder_path)
        if not os.path.isdir(folder_path):
            raise ValueError(f"Random Image Loader: folder not found: {folder_path!r}")

        files = list_images(folder_path, recursive)
        if not files:
            raise ValueError(f"Random Image Loader: no images found in {folder_path!r}")

        img_path = random.Random(seed).choice(files)
        with Image.open(img_path) as opened:
            img = ImageOps.exif_transpose(opened).convert("RGB")

        w, h = img.size
        image = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).unsqueeze(0)
        info = f"{os.path.relpath(img_path, folder_path)} ({w}×{h})"

        return {
            "ui": {"preview": [save_preview(img)], "info": [info]},
            "result": (image,),
        }
