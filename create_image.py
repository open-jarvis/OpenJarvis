from PIL import Image, ImageDraw
import os

# Create a detailed scene image
width, height = 800, 600
img = Image.new('RGB', (width, height), '#F5F5DC')
draw = ImageDraw.Draw(img)

# Background
draw.rectangle([0, 0, width, height-100], '#D2B48C')
draw.rectangle([0, height-100, width, height], '#8B4513')

# Table
table_y = height - 80
draw.rectangle([100, table_y, 700, height], '#654321')

# Robot
draw.ellipse([320, 200, 480, 320], '#4682B4')
draw.ellipse([360, 160, 440, 200], '#4682B4')
draw.ellipse([380, 180, 420, 200], 'white')
draw.ellipse([420, 180, 460, 200], 'white')
draw.arc([390, 190, 450, 210], 0, 180, '#FF6347')
draw.line([420, 160, 420, 130], '#FF4500')
draw.circle([420, 130], 5, '#FF4500')

# Book
draw.rectangle([400, table_y+20, 540, table_y+120], '#8B0000')
draw.rectangle([410, table_y+30, 530, table_y+110], '#FFE4B5')

# Cups
draw.ellipse([200, table_y+30, 240, table_y+70], '#8B4513')
draw.ellipse([210, table_y+40, 230, table_y+60], '#FFF8DC')
draw.ellipse([560, table_y+30, 600, table_y+70], '#8B4513')
draw.ellipse([570, table_y+40, 590, table_y+60], '#FFF8DC')

# Shelves
draw.rectangle([50, 100, 200, 180], '#A0522D')
for i in range(5):
    draw.rectangle([55+i*20, 110, 195+i*20, 170], ['#FF6347','#4169E1','#32CD32','#FFD700','#9370DB'][i%5])

# Plant
draw.ellipse([650, 150, 700, 210], '#228B22')
draw.ellipse([660, 160, 690, 200], '#32CD32')

img.save('robot_cafe.png')
print("Done!")