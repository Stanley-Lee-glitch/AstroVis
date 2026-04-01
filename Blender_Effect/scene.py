import bpy
import os

class SceneManager:
    def __init__(self, scene_name="AstroScene", export_dir="./output"):
        self.scene_name = scene_name
        self.export_dir = os.path.abspath(export_dir)
        os.makedirs(self.export_dir, exist_ok=True)
        
        self.objects = {}  # track all objects
        self.scene = bpy.context.scene
        self.scene.name = scene_name
    
    def clear_scene(self):
        bpy.ops.wm.read_homefile(use_empty=True)
        self.objects = {}
    
    def add_object(self, obj_name, obj_data):

        self.objects[obj_name] = obj_data
        # actual Blender object creation happens here or in objects.py

    def set_camera(self, location=(0,0,10), look_at=(0,0,0)):
        cam = bpy.data.objects.get("Camera")
        if not cam:
            bpy.ops.object.camera_add(location=location)
            cam = bpy.context.object
        cam.location = location
        cam.rotation_euler = (0,0,0)  # optionally compute proper rotation
        self.scene.camera = cam

    def set_light(self, location=(0,0,10)):
        bpy.ops.object.light_add(type='SUN', location=location)

    def get_export_path(self, filename="output.png"):
        return os.path.join(self.export_dir, filename)
