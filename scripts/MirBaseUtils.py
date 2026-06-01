import urllib.request
import gzip
import re
import json
from pathlib import Path
from collections import defaultdict


MIRBASE_URL = "https://mirbase.org/ftp/CURRENT/miRNA.dat.gz"
LOCAL_GZ    = Path("miRNA.dat.gz")
LOOKUP_FILE = Path("mirbase_lookup.json")


def download_mirbase():
    print("Downloading miRNA.dat.gz ...")
    urllib.request.urlretrieve(MIRBASE_URL, LOCAL_GZ)
    print(f"Saved to {LOCAL_GZ} ({LOCAL_GZ.stat().st_size / 1e6:.1f} MB)")



# Call R's miRBaseConverter from Python
import rpy2.robjects as ro
from rpy2.robjects.packages import importr

mirbase = importr('miRBaseConverter')

def convert_to_v22(mirna_names: list[str]) -> dict:
    r_vec = ro.StrVector(mirna_names)
    result = mirbase.miRNAVersionConvert(r_vec, targetVersion="v22", exact=True)
    df = dict(zip(result.names, list(result)))
    return {orig: target for orig, target in zip(df['OriginalName'], df['TargetName'])}