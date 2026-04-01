def setup_particle_mesh(
    frames_data, # list of SPHParticleData, one per frame
    object_name: str = "star",
    obj: bpy.types.Object = None,
    position_scale=1.0,
    center=True
):

    if isinstance(frames_data, dict):
        frames_data = [frames_data]
    
    num_frames = len(frames_data)
    num_particles = frames_data[0].coordinates.shape[0]

    if obj is None:
        obj = create_object(object_name)
    
    mesh = obj.data
    if len(mesh.vertices) != num_particles:
        mesh.clear_geometry()
        mesh.from_pydata([(0.0, 0.0, 0.0)] * num_particles, [], [])
        mesh.update()

    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = num_frames - 1

    # Create attributes if not existing
    for name in frames_data[0].fields.keys():
        if name not in mesh.attributes:
           mesh.attributes.new(name=name, type='FLOAT', domain='POINT')
           print(f"Created attribute '{name}' for particle mesh.")

    def make_handler(obj, frames_data, num_frames):
        def _update_particles(scene):
            f = scene.frame_current
            if f < 0 or f >= num_frames:
                return

            frame = frames_data[f]

            pos = frame.coordinates.astype(np.float32) * position_scale
            if center:
                pos -= pos.mean(axis=0)

            mesh.vertices.foreach_set("co", pos.ravel())
            
            for name, values in frame.fields.items():
                mesh.attributes[name].data.foreach_set(
                    "value", np.ravel(values, order='C')
                )
                
            mesh.update()
            
            _update_particles._object_name = obj.name
            
        return _update_particles

    remove_existing_handler(obj.name)
    handler = make_handler(obj, frames_data, num_frames)
    bpy.app.handlers.frame_change_post.append(handler)
    
    print(bpy.context.collection.name)
    
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)


    print(f"Particle mesh animation registered ({num_frames} frames).")


def setup_surface_mesh(
    frames_data,      # list of surface_data dict, one per frame 
    ## surface_data: {vertices: list of (x,y,z), faces: list of (i,j,k), normals: list of (nx,ny,nz)}
    
    object_name: str = "surface_mesh",
    obj: bpy.types.Object = None,
    position_scale=1.0,
    center = True
    ): 
    
    if isinstance(frames_data, dict):
        frames_data = [frames_data]

    num_frames = len(frames_data)
    print(f"No. of frames for surface mesh animation: {num_frames}")
    
    if obj is None:
        obj = create_object(object_name)
    
    scene = bpy.context.scene
    scene.frame_start = 0
    scene.frame_end = num_frames - 1
    
    def make_handler(obj, frames_data, num_frames):
        def _update_mesh(scene):
            f = scene.frame_current
            if f < 0 or f >= num_frames:
                return

            frame = frames_data[f]

            verts_array = np.array(frame["vertices"], dtype=np.float32) * position_scale

            if center:
                verts_array -= verts_array.mean(axis=0)

            mesh = obj.data
            mesh.clear_geometry()
            mesh.from_pydata(verts_array.tolist(), [], frame["faces"])
            mesh.update()
            
            _update_mesh._object_name = obj.name  # tag for tracing

        return _update_mesh

    remove_existing_handler(obj.name)  # ensure no duplicate handlers for this object
    handler = make_handler(obj, frames_data, num_frames)
    bpy.app.handlers.frame_change_post.append(handler)
    
    print(bpy.context.collection.name)
    if obj.name not in bpy.context.collection.objects:
        bpy.context.collection.objects.link(obj)
            
    print(f"{object_name} surface animation registered ({num_frames} frames).")
   

    return obj