import sys
sys.path.append("../../..")

from AstroVis.backend import export_volume_vdb_sequence

start_frame = 120
end_frame = 129

export_volume_vdb_sequence(input_dir="Data", output_dir="Output", object_name="Star_Formation", 
                           start_frame=start_frame, end_frame=end_frame,
                            vtype="gas", field="density", log=True,
                            preview_dir="Plots",preview_every=1, scale=100,
                            zip_output=False, delete_unzipped=False,)
