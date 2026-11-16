"""Write poster/aspect.json: height/width of every figure, so the poster lays images out at their true shape."""
import glob, json, os
from PIL import Image
here = os.path.dirname(os.path.abspath(__file__))
out = {os.path.basename(f): round(Image.open(f).height / Image.open(f).width, 4) for f in sorted(glob.glob(os.path.join(here, "..", "figures", "*.png")))}
json.dump(out, open(os.path.join(here, "aspect.json"), "w"), indent=1); print(out)
