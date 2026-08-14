"""Blender integration for NORA AI — automation via Python API."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
import json

logger = logging.getLogger(__name__)


class BlenderDetector:
    """Detect Blender installation and version."""

    @staticmethod
    def find_blender() -> Optional[Path]:
        """Find Blender executable in common locations."""
        import platform
        import shutil

        # Try standard executable name first
        blender_exe = "blender.exe" if platform.system() == "Windows" else "blender"
        path = shutil.which(blender_exe)
        if path:
            return Path(path)

        # Common installation paths
        common_paths = {
            "Windows": [
                "C:\\Program Files\\Blender Foundation\\Blender 4.1\\blender.exe",
                "C:\\Program Files (x86)\\Blender Foundation\\Blender 4.1\\blender.exe",
            ],
            "Darwin": [
                "/Applications/Blender.app/Contents/MacOS/Blender",
            ],
            "Linux": [
                "/usr/bin/blender",
                "/snap/bin/blender",
            ],
        }

        system = platform.system()
        for candidate in common_paths.get(system, []):
            path = Path(candidate)
            if path.exists():
                return path

        return None

    @staticmethod
    def get_version(blender_path: Path) -> Optional[str]:
        """Get Blender version."""
        try:
            result = subprocess.run(
                [str(blender_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Output: "Blender 4.1.0"
            return result.stdout.strip().split()[-1]
        except Exception as e:
            logger.warning(f"Failed to get Blender version: {e}")
            return None


class BlenderScript:
    """Builder for Blender Python scripts."""

    def __init__(self, name: str = "nora_script"):
        self.name = name
        self.imports: List[str] = ["import bpy"]
        self.code_lines: List[str] = []

    def add_import(self, module: str) -> None:
        """Add import statement."""
        if f"import {module}" not in self.imports:
            self.imports.append(f"import {module}")

    def add_code(self, code: str) -> None:
        """Add Python code."""
        self.code_lines.append(code)

    def clear_scene(self) -> None:
        """Generate code to clear the scene."""
        self.add_code(
            """
# Clear existing mesh objects
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
"""
        )

    def create_object(self, obj_type: str, name: str) -> None:
        """Generate code to create an object."""
        if obj_type == "cube":
            self.add_code(f"bpy.ops.mesh.primitive_cube_add(name='{name}')")
        elif obj_type == "sphere":
            self.add_code(f"bpy.ops.mesh.primitive_uv_sphere_add(name='{name}')")
        elif obj_type == "camera":
            self.add_code(f"bpy.ops.object.camera_add(name='{name}')")
        elif obj_type == "light":
            self.add_code(f"bpy.ops.object.light_add(type='POINT', name='{name}')")
        else:
            logger.warning(f"Unknown object type: {obj_type}")

    def set_object_location(self, obj_name: str, x: float, y: float, z: float) -> None:
        """Generate code to set object location."""
        self.add_code(
            f"""
obj = bpy.data.objects['{obj_name}']
obj.location = ({x}, {y}, {z})
"""
        )

    def render_to_file(self, output_path: str, format: str = "PNG") -> None:
        """Generate code to render to file."""
        self.add_code(
            f"""
# Set render output
bpy.context.scene.render.filepath = '{output_path}'
bpy.context.scene.render.image_settings.file_format = '{format}'

# Render
bpy.ops.render.render(write_still=True)
print(f'Render saved to {output_path}')
"""
        )

    def generate(self) -> str:
        """Generate complete Python script."""
        script = "\n".join(self.imports)
        script += "\n\n"
        script += "\n".join(self.code_lines)
        return script

    def save(self, path: Path) -> None:
        """Save script to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.generate())
        logger.info(f"Blender script saved: {path}")


class BlenderController:
    """Control Blender and execute scripts."""

    def __init__(self):
        self.blender_path = BlenderDetector.find_blender()
        self.version = (
            BlenderDetector.get_version(self.blender_path)
            if self.blender_path
            else None
        )
        logger.info(
            f"Blender detected: {self.blender_path} (v{self.version})"
        )

    def is_available(self) -> bool:
        """Check if Blender is installed."""
        return self.blender_path is not None and self.blender_path.exists()

    def run_script(self, script_path: Path, background: bool = True) -> bool:
        """Execute a Blender Python script."""
        if not self.is_available():
            logger.error("Blender is not installed")
            return False

        try:
            cmd = [str(self.blender_path)]
            if background:
                cmd.append("--background")
            cmd.extend(["--python", str(script_path)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode == 0:
                logger.info(f"Blender script executed successfully")
                return True
            else:
                logger.error(f"Blender script failed: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("Blender script timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to execute Blender script: {e}")
            return False

    def open_blend_file(self, blend_file: Path) -> bool:
        """Open a .blend file in Blender (foreground)."""
        if not self.is_available():
            logger.error("Blender is not installed")
            return False

        try:
            subprocess.Popen([str(self.blender_path), str(blend_file)])
            return True
        except Exception as e:
            logger.error(f"Failed to open Blender: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get Blender status."""
        return {
            "installed": self.is_available(),
            "path": str(self.blender_path) if self.blender_path else None,
            "version": self.version,
        }


__all__ = [
    "BlenderDetector",
    "BlenderScript",
    "BlenderController",
]
