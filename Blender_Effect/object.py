import bpy
'''
Utilities for managing Blender objects, shading and modifiers.
'''


def duplicate_object(original_obj, new_name):
    """
    Duplicate object data. Remove existing object if name collide.
    """
    new_obj = bpy.data.objects.get(new_name)
    if new_obj is not None:
        bpy.data.objects.remove(new_obj)

    new_obj = bpy.data.objects.new(new_name, original_obj.data)  
    bpy.context.collection.objects.link(new_obj)             
    return new_obj


def resolve_object(obj):
    if isinstance(obj, bpy.types.Object):
        return obj
    
    elif isinstance(obj, str):
        obj_ref = bpy.data.objects.get(obj)
        
        if not obj_ref:
            raise ValueError(f"Object named '{obj}' not found in the scene.")
            
        return obj_ref
    else:
        raise TypeError("obj must be bpy.types.Object or a string")
    
def create_object(obj_name):
    """Create or overwrite object and link to active collection."""
    if obj_name in bpy.data.meshes:
        bpy.data.meshes.remove(bpy.data.meshes[obj_name])
    if obj_name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[obj_name])

    mesh = bpy.data.meshes.new(obj_name)
    obj = bpy.data.objects.new(obj_name, mesh)
    
    bpy.context.collection.objects.link(obj)
    
    return obj

def set_object_shader(obj, shader_name = None):
    """
    Set the shader type of an object. If shader_name is None, try to find a material containing the object's name.
    """
    obj = resolve_object(obj)

    if shader_name is not None:
        if isinstance(shader_name, str):
            mat = bpy.data.materials.get(shader_name)
            
                
        elif isinstance(shader_name, bpy.types.Material):
            mat = shader_name
            
        else:
            raise TypeError("shader_name must be a string or bpy.types.Material")
        
        if mat is None:
                print(f"Material '{shader_name}' not found.")
        
    else:
        trial = [m for m in bpy.data.materials if obj.name in m.name]
        print(trial)
        mat = trial[0]
        
        if mat is None:
            print(f"No matching material found containing '{obj.name}'.")
        
    if mat is not None:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        print(f"Set shader '{mat.name}' for object '{obj.name}'.")
        


def list_modifiers(obj):
    """
    Print all modifiers on the given object with their index in the stack.
    
    Args:
        obj: The Blender object or String
    """
    obj = resolve_object(obj)

    print(f"Modifiers on object '{obj.name}':")
    for idx, mod in enumerate(obj.modifiers):
        print(f"  {idx}: {mod.name} ({mod.type})")


def delete_modifier(obj, mod_name: str):
    """
    Delete a modifier from an object if it exists.
    """
    obj = resolve_object(obj)

    mod = obj.modifiers.get(mod_name)
    if mod:
        obj.modifiers.remove(mod)
        print(f"Deleted modifier '{mod_name}'")
    else:
        print(f"Modifier '{mod_name}' not found")


def move_modifier(obj, mod_name: str, direction: str = 'up'):
    """
    Move a modifier up or down.
    """
    obj = resolve_object(obj)

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    if direction == 'up':
        bpy.ops.object.modifier_move_up(modifier=mod_name)
        print(f"Moved modifier '{mod_name}' up")
    elif direction == 'down':
        bpy.ops.object.modifier_move_down(modifier=mod_name)
        print(f"Moved modifier '{mod_name}' down")
    else:
        raise ValueError("Direction must be 'up' or 'down'")


def add_gn_modifer(obj, mod_name: str):
    """
    Add a modifier WITH gn_node group. 
    Delete existing modifier and gn_node group with the same name.
    """
    obj = resolve_object(obj)

    if mod_name in bpy.data.node_groups: 
        bpy.data.node_groups.remove(bpy.data.node_groups[mod_name]) 

    gn_group = bpy.data.node_groups.new(type="GeometryNodeTree", name=mod_name)
    gn_group.description = f"mod_name"
    gn_group.is_modifier = True

    if mod_name in bpy.data.objects[obj.name].modifiers:
        bpy.data.objects[obj.name].modifiers.remove(bpy.data.objects[obj.name].modifiers[mod_name])
    gn_mod = obj.modifiers.new(mod_name, 'NODES')
    gn_mod.node_group = gn_group
    
    return gn_mod, gn_group
