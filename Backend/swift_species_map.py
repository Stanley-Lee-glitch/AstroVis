import numpy as np

ELEMENT_MAP = {
    "H": [("HI", 1), ("HII", 2), ("Hm", 3)],
    "He": [("HeI", 4), ("HeII", 5), ("HeIII", 6)],
    "C": [("CI", 7), ("CII", 8), ("CIII", 9), ("CIV", 10), ("CV", 11), ("CVI", 12), ("CVII", 13), ("Cm", 14)],
    "N": [("NI", 15), ("NII", 16), ("NIII", 17), ("NIV", 18), ("NV", 19), ("NVI", 20), ("NVII", 21), ("NVIII", 22)],
    "O": [("OI", 23), ("OII", 24), ("OIII", 25), ("OIV", 26), ("OV", 27), ("OVI", 28), ("OVII", 29), ("OVIII", 30), ("OIX", 31), ("Om", 32)],
    "Ne": [("NeI", 33), ("NeII", 34), ("NeIII", 35), ("NeIV", 36), ("NeV", 37), ("NeVI", 38), ("NeVII", 39), ("NeVIII", 40), ("NeIX", 41), ("NeX", 42), ("NeXI", 43)],
    "Mg": [("MgI", 44), ("MgII", 45), ("MgIII", 46), ("MgIV", 47), ("MgV", 48), ("MgVI", 49), ("MgVII", 50), ("MgVIII", 51), ("MgIX", 52), ("MgX", 53), ("MgXI", 54), ("MgXII", 55), ("MgXIII", 56)],
    "Si": [("SiI", 57), ("SiII", 58), ("SiIII", 59), ("SiIV", 60), ("SiV", 61), ("SiVI", 62), ("SiVII", 63), ("SiVIII", 64), ("SiIX", 65), ("SiX", 66), ("SiXI", 67), ("SiXII", 68), ("SiXIII", 69), ("SiXIV", 70), ("SiXV", 71)],
    "S": [("SI", 72), ("SII", 73), ("SIII", 74), ("SIV", 75), ("SV", 76), ("SVI", 77), ("SVII", 78), ("SVIII", 79), ("SIX", 80), ("SX", 81), ("SXI", 82), ("SXII", 83), ("SXIII", 84), ("SXIV", 85), ("SXV", 86), ("SXVI", 87), ("SXVII", 88)],
    "Ca": [("CaI", 89), ("CaII", 90), ("CaIII", 91), ("CaIV", 92), ("CaV", 93), ("CaVI", 94), ("CaVII", 95), ("CaVIII", 96), ("CaIX", 97), ("CaX", 98), ("CaXI", 99), ("CaXII", 100), ("CaXIII", 101), ("CaXIV", 102), ("CaXV", 103), ("CaXVI", 104), ("CaXVII", 105), ("CaXVIII", 106), ("CaXIX", 107), ("CaXX", 108), ("CaXXI", 109)],
    "Fe": [("FeI", 110), ("FeII", 111), ("FeIII", 112), ("FeIV", 113), ("FeV", 114), ("FeVI", 115), ("FeVII", 116), ("FeVIII", 117), ("FeIX", 118), ("FeX", 119), ("FeXI", 120), ("FeXII", 121), ("FeXIII", 122), ("FeXIV", 123), ("FeXV", 124), ("FeXVI", 125), ("FeXVII", 126), ("FeXVIII", 127), ("FeXIX", 128), ("FeXX", 129), ("FeXXI", 130), ("FeXXII", 131), ("FeXXIII", 132), ("FeXXIV", 133), ("FeXXV", 134), ("FeXXVI", 135), ("FeXXVII", 136)]
}

MOLECULE_MAP = {
    "H2": 137, "H2p": 138, "H3p": 139, "OH": 140, "H2O": 141,
    "C2": 142, "O2": 143, "HCOp": 144, "CH": 145, "CH2": 146, "CH3p": 147,
    "CO": 148, "CHp": 149, "CH2p": 150, "OHp": 151, "H2Op": 152, "H3Op": 153,
    "COp": 154, "HOCp": 155, "O2p": 156
}



def generate_species_fraction_fields(ds, species):
    """
    Automatically generate fraction getter functions for species fraction.
    Returns a dict: { "<species>_fraction": getter_function }
    """
    ad = ds.all_data()
    fields = {}

    # --- Handle elements ---
    if species in ELEMENT_MAP.keys():
        indices = [idx for _, idx in ELEMENT_MAP[species]]  # all indices for this element
        for name, idx in ELEMENT_MAP[species]:
            def getter(idx=idx, indices=indices):
                all_species = ad['PartType0', "SpeciesFractions"]
                data = np.array(all_species[:, idx])
                total = np.sum(all_species[:, indices], axis=1)
                mask = total > 0
                data[mask] = data[mask] / total[mask]
                return np.ascontiguousarray(data)

            fields[f"{name}_fraction"] = getter

    # --- Handle molecules ---
    elif species in MOLECULE_MAP.keys():
        idx = MOLECULE_MAP[species]
        def getter(idx=idx):
            all_species = ad['PartType0', "SpeciesFractions"]
            data = np.array(all_species[:, idx])
            return np.ascontiguousarray(data)

        fields[f"{mol}_fraction"] = getter
    
    else:
        print(f"Warning: Species '{species}' not found in ELEMENT_MAP or MOLECULE_MAP. Please write the callable function manually.")

    return fields