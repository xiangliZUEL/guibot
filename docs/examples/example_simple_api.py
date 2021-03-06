#!/usr/bin/python3

# Only needed if not installed system wide
import sys
sys.path.insert(0, '../..')


# Program start here
#
# Load images/all_shapes.png with a picture viewer
# and it will print "Shapes exist"


from guibot.guibot_simple import *


initialize()
add_path('images')

if exists('all_shapes'):
    print('Shapes exist')
else:
    print('Shapes do not exist')
