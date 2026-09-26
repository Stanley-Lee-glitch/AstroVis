import os

import bpy
from mathutils import Vector


class SceneManager:
    def __init__(self, scene_name="AstroScene", export_dir=None):
        self.scene_name = scene_name
        if export_dir is None:
            export_dir = os.path.join(os.path.expanduser("~"), "AstroVis", "output")
        self.export_dir = os.path.abspath(export_dir)
        os.makedirs(self.export_dir, exist_ok=True)

        self.objects = {}
        self.scene = bpy.context.scene
        self.scene.name = scene_name

    def refresh_scene(self):
        self.scene = bpy.context.scene
        self.scene.name = self.scene_name
        return self.scene

    def clear_scene(self, use_empty=True):
        if use_empty:
            bpy.ops.wm.read_homefile(use_empty=True)
            self.objects = {}
            return self.refresh_scene()

        self.clear_all()
        return self.scene

    def clear_all(
        self,
        clear_materials=True,
        clear_collections=True,
        clear_world=False,
        clear_node_groups=False,
        clear_images=False,
    ):
        self.clear_objects(clear_data=False)
        if clear_collections:
            self.clear_collections()
        if clear_materials:
            self.clear_materials()
        self.clear_orphan_data()
        if clear_node_groups:
            self.clear_node_groups()
        if clear_images:
            self.clear_images()
        if clear_world:
            self.set_world_background()
        self.objects = {}
        return self.scene

    def _remove_animation_handler(self, obj_name):
        from ..Blender_Import.mesh_animation import remove_existing_handler

        remove_existing_handler(obj_name)

    def clear_objects(self, object_types=None, exclude_names=None, clear_data=True):
        object_types = set(object_types) if object_types is not None else None
        exclude_names = set(exclude_names or [])

        removed = []
        for obj in list(bpy.data.objects):
            if obj.name in exclude_names:
                continue
            if object_types is not None and obj.type not in object_types:
                continue
            self._remove_animation_handler(obj.name)
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)

        for obj_name in removed:
            self.objects.pop(obj_name, None)

        if clear_data:
            self.clear_orphan_data()

        return removed

    def clear_mesh_objects(self, exclude_names=None):
        return self.clear_objects(object_types={"MESH"}, exclude_names=exclude_names)

    def clear_volume_objects(self, exclude_names=None):
        return self.clear_objects(object_types={"VOLUME"}, exclude_names=exclude_names)

    def clear_lights(self, exclude_names=None):
        return self.clear_objects(object_types={"LIGHT"}, exclude_names=exclude_names)

    def clear_cameras(self, exclude_names=None):
        return self.clear_objects(object_types={"CAMERA"}, exclude_names=exclude_names)

    def clear_collections(self, exclude_names=None):
        exclude_names = set(exclude_names or [])
        root_collection = self.scene.collection
        removed = []

        for collection in list(bpy.data.collections):
            if collection == root_collection or collection.name in exclude_names:
                continue
            removed.append(collection.name)
            bpy.data.collections.remove(collection)

        return removed

    def _remove_id_blocks(self, id_collection, only_unused=True, exclude_names=None):
        exclude_names = set(exclude_names or [])
        removed = []

        for data_block in list(id_collection):
            if data_block.name in exclude_names:
                continue
            if only_unused and getattr(data_block, "users", 0) > 0:
                continue
            removed.append(data_block.name)
            id_collection.remove(data_block)

        return removed

    def clear_materials(self, only_unused=True, exclude_names=None):
        return self._remove_id_blocks(bpy.data.materials, only_unused=only_unused, exclude_names=exclude_names)

    def clear_node_groups(self, only_unused=True, exclude_names=None):
        return self._remove_id_blocks(bpy.data.node_groups, only_unused=only_unused, exclude_names=exclude_names)

    def clear_images(self, only_unused=True, exclude_names=None):
        return self._remove_id_blocks(bpy.data.images, only_unused=only_unused, exclude_names=exclude_names)

    def clear_orphan_data(self):
        removed = {
            "meshes": self._remove_id_blocks(bpy.data.meshes, only_unused=True),
            "volumes": self._remove_id_blocks(bpy.data.volumes, only_unused=True),
            "lights": self._remove_id_blocks(bpy.data.lights, only_unused=True),
            "cameras": self._remove_id_blocks(bpy.data.cameras, only_unused=True),
            "curves": self._remove_id_blocks(bpy.data.curves, only_unused=True),
        }

        if hasattr(bpy.data, "pointclouds"):
            removed["pointclouds"] = self._remove_id_blocks(bpy.data.pointclouds, only_unused=True)

        return removed

    def ensure_collection(self, collection_name):
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            collection = bpy.data.collections.new(collection_name)
            self.scene.collection.children.link(collection)
        return collection

    def add_object(self, obj_name, obj_data):
        self.objects[obj_name] = obj_data
        return obj_data

    def _look_at_rotation(self, location, look_at):
        direction = Vector(look_at) - Vector(location)
        if direction.length == 0:
            raise ValueError("Camera or light location must differ from look_at.")
        return direction.to_track_quat("-Z", "Y").to_euler()

    def set_camera(
        self,
        name="Camera",
        location=(0, 0, 10),
        look_at=(0, 0, 0),
        lens=50.0,
        clip_start=0.1,
        clip_end=10000.0,
    ):
        cam = bpy.data.objects.get(name)
        if cam is None or cam.type != "CAMERA":
            bpy.ops.object.camera_add(location=location)
            cam = bpy.context.object
            cam.name = name
            cam.data.name = name

        cam.location = location
        cam.rotation_euler = self._look_at_rotation(location, look_at)
        cam.data.lens = lens
        cam.data.clip_start = clip_start
        cam.data.clip_end = clip_end
        self.scene.camera = cam
        self.objects[cam.name] = cam
        return cam

    def add_light(
        self,
        name=None,
        light_type="SUN",
        location=(0, 0, 10),
        rotation=(0, 0, 0),
        energy=10.0,
        color=(1.0, 1.0, 1.0),
        size=1.0,
        look_at=None,
        collection_name="Lights",
    ):
        bpy.ops.object.light_add(type=light_type, location=location, rotation=rotation)
        light_object = bpy.context.object
        light_data = light_object.data

        if name is not None:
            light_object.name = name
            light_data.name = name

        light_data.energy = energy
        light_data.color = color

        if hasattr(light_data, "shadow_soft_size"):
            light_data.shadow_soft_size = size
        if hasattr(light_data, "size"):
            light_data.size = size
        if hasattr(light_data, "angle") and light_type == "SUN":
            light_data.angle = size
        if hasattr(light_data, "spot_size") and light_type == "SPOT":
            light_data.spot_size = size

        if look_at is not None:
            light_object.rotation_euler = self._look_at_rotation(location, look_at)

        target_collection = self.ensure_collection(collection_name)
        for existing_collection in list(light_object.users_collection):
            if existing_collection != target_collection:
                existing_collection.objects.unlink(light_object)
        if target_collection not in light_object.users_collection:
            target_collection.objects.link(light_object)

        self.objects[light_object.name] = light_object
        return light_object

    def set_light(self, location=(0, 0, 10), **kwargs):
        return self.add_light(location=location, **kwargs)

    def set_lights(self, light_configs, clear_existing=False, collection_name="Lights"):
        if clear_existing:
            self.clear_lights()
            self.clear_orphan_data()

        lights = []
        for idx, config in enumerate(light_configs):
            light_kwargs = dict(config)
            light_kwargs.setdefault("name", f"{collection_name}_{idx:03d}")
            light_kwargs.setdefault("collection_name", collection_name)
            lights.append(self.add_light(**light_kwargs))
        return lights

    def add_light_grid(
        self,
        name_prefix="Fill",
        count_x=3,
        count_y=3,
        spacing=(2.0, 2.0),
        center=(0.0, 0.0, 0.0),
        height=5.0,
        light_type="POINT",
        energy=1000.0,
        color=(1.0, 1.0, 1.0),
        size=0.25,
        look_at=(0.0, 0.0, 0.0),
        collection_name="Lights",
    ):
        lights = []
        offset_x = 0.5 * (count_x - 1) * spacing[0]
        offset_y = 0.5 * (count_y - 1) * spacing[1]

        for ix in range(count_x):
            for iy in range(count_y):
                location = (
                    center[0] + ix * spacing[0] - offset_x,
                    center[1] + iy * spacing[1] - offset_y,
                    center[2] + height,
                )
                light_name = f"{name_prefix}_{ix}_{iy}"
                lights.append(
                    self.add_light(
                        name=light_name,
                        light_type=light_type,
                        location=location,
                        energy=energy,
                        color=color,
                        size=size,
                        look_at=look_at,
                        collection_name=collection_name,
                    )
                )

        return lights

    def set_world_background(self, color=(0.0, 0.0, 0.0, 1.0), strength=1.0):
        world = self.scene.world
        if world is None:
            world = bpy.data.worlds.new("World")
            self.scene.world = world

        world.use_nodes = True
        node_tree = world.node_tree
        nodes = node_tree.nodes
        links = node_tree.links
        nodes.clear()

        output_node = nodes.new(type="ShaderNodeOutputWorld")
        background_node = nodes.new(type="ShaderNodeBackground")
        background_node.inputs["Color"].default_value = color
        background_node.inputs["Strength"].default_value = strength
        links.new(background_node.outputs["Background"], output_node.inputs["Surface"])
        return world

    def set_render(
        self,
        engine="CYCLES",
        samples=128,
        resolution=(1920, 1080),
        transparent=False,
        filepath=None,
        fps=None,
    ):
        render = self.scene.render
        render.engine = engine
        render.resolution_x = int(resolution[0])
        render.resolution_y = int(resolution[1])
        render.film_transparent = transparent

        if fps is not None:
            render.fps = int(fps)

        if filepath is not None:
            render.filepath = self.get_export_path(filepath)

        if engine == "CYCLES" and hasattr(self.scene, "cycles"):
            self.scene.cycles.samples = int(samples)

        return render

    def get_export_path(self, filename="output.png"):
        return os.path.join(self.export_dir, filename)
