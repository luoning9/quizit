from pathlib import Path
from PIL import Image, ImageDraw
import json
from split_columns_layout import analyze_page_layout, compute_column_text_bounds, find_blank_rectangle_in_strip, lines_in_rect

pdf = Path('/Users/jason/Downloads/53quiz_sample.pdf')
page_no = 1
layout = analyze_page_layout(pdf, page_no)
data = json.loads(Path('tmp/columns_questions/page_manifest.json').read_text())
page = next(entry for entry in data if entry['page'] == page_no)
image = Image.open(Path('tmp/columns_questions/rendered_pages/page_001.png')).convert('RGB')
scale_x = image.width / page['page_width']
scale_y = image.height / page['page_height']
page_height = image.height / scale_y

columns = list(layout.columns)
column_bounds = {}
for column in columns:
    rows = [line for line in lines_in_rect(layout.lines, column.x_min, column.x_max, 0.0, page_height) if line.text.strip()]
    anchors = [a for a in layout.anchors if column.x_min <= a.x_min <= column.x_max]
    anchors.sort(key=lambda a: a.y_min)
    column_bounds[column.index] = compute_column_text_bounds(column, anchors, rows)

draw = ImageDraw.Draw(image)
for idx, column in enumerate(columns):
    xmin, xmax = column_bounds[column.index]
    prev = xmin - 24.0 if idx == 0 else column_bounds[columns[idx - 1].index][1]
    left_rect = find_blank_rectangle_in_strip(image, prev, xmin, scale_x, scale_y)
    print(column)
    print(left_rect)
    nextx = xmax + 24.0 if idx == len(columns) - 1 else column_bounds[columns[idx + 1].index][0]
    right_rect = find_blank_rectangle_in_strip(image, xmax, nextx, scale_x, scale_y)
    cpage = page['columns'][column.index]
    x0, x1 = int(column.x_min * scale_x), int(column.x_max * scale_x)
    y0, y1 = int(cpage['y_min'] * scale_y), int(cpage['y_max'] * scale_y)
    draw.rectangle((x0, y0, x1, y1), outline='lime', width=3)
    draw.text((x0 + 4, y0 + 4), f"C{column.index+1}", fill='lime')
    if left_rect:
        l0, lt, l1, lb = left_rect
        draw.rectangle((int(l0 * scale_x), int(lt * scale_y), int(l1 * scale_x), int(lb * scale_y)), outline='red', width=4)
    if right_rect:
        r0, rt, r1, rb = right_rect
        draw.rectangle((int(r0 * scale_x), int(rt * scale_y), int(r1 * scale_x), int(rb * scale_y)), outline='blue', width=4)
    draw.line((x0, y0, x1, y0), fill='yellow', width=2)
    draw.line((x0, y1, x1, y1), fill='orange', width=2)

image.save('tmp/columns_questions/page_001_rects_red_blue.png')
