"""Create the synthetic product illustration used only by browser tests."""
from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new('RGB', (320, 200), '#dddddd')
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((35, 40, 285, 150), radius=8, fill='#aaaaaa', outline='#333333', width=3)
for x in (65, 255):
    for y in (65, 125):
        draw.ellipse((x-10, y-10, x+10, y+10), fill='#dddddd', outline='#444444', width=2)
draw.rectangle((130, 65, 190, 125), fill='#888888', outline='#333333', width=2)
draw.text((105, 170), 'DEMO FIXTURE A', fill='#333333')
image.save(Path(__file__).with_name('recipe-part.png'))
